import argparse
import csv
import datetime as dt
import math
import re
import sqlite3
from pathlib import Path


WORD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z'\-]*$")


def to_int(value):
    if value is None:
        return 0
    text = str(value).strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def normalize_word(word):
    return (word or "").strip()


def is_valid_headword(word):
    w = normalize_word(word)
    if not w:
        return False
    if " " in w:
        return False
    if any(ch.isdigit() for ch in w):
        return False
    if w[0] in "-'" or w[-1] in "-'":
        return False
    return bool(WORD_PATTERN.match(w))


def split_tags(tag_value):
    text = (tag_value or "").strip().lower()
    if not text:
        return set()
    return {x for x in text.split() if x}


def field_non_empty(value):
    return bool((value or "").strip())


def info_density_score(row):
    score = 0.0
    if field_non_empty(row.get("phonetic")):
        score += 30
    if field_non_empty(row.get("translation")):
        score += 40
    if field_non_empty(row.get("definition")):
        score += 40
    return score


def priority_score(row, is_ielts_tag):
    collins = max(0, to_int(row.get("collins")))
    oxford = max(0, to_int(row.get("oxford")))
    frq = max(0, to_int(row.get("frq")))
    bnc = max(0, to_int(row.get("bnc")))
    word = normalize_word(row.get("word"))

    score = 0.0
    if is_ielts_tag:
        score += 10_000

    score += collins * 220
    if oxford > 0:
        score += 260

    if frq > 0:
        score += max(0.0, 300 - math.log10(frq + 1) * 80)
    if bnc > 0:
        score += max(0.0, 220 - math.log10(bnc + 1) * 60)

    score += info_density_score(row)

    if word and word[0].isupper():
        score -= 180
    if "-" in word:
        score -= 25

    return round(score, 3)


def row_payload(row, is_ielts_tag, source):
    return {
        "word": normalize_word(row.get("word")),
        "word_lower": normalize_word(row.get("word")).lower(),
        "phonetic": (row.get("phonetic") or "").strip(),
        "definition_en": (row.get("definition") or "").strip(),
        "definition_zh": (row.get("translation") or "").strip(),
        "pos": (row.get("pos") or "").strip(),
        "collins": max(0, to_int(row.get("collins"))),
        "oxford": max(0, to_int(row.get("oxford"))),
        "tag": (row.get("tag") or "").strip(),
        "bnc": max(0, to_int(row.get("bnc"))),
        "frq": max(0, to_int(row.get("frq"))),
        "exchange": (row.get("exchange") or "").strip(),
        "detail": (row.get("detail") or "").strip(),
        "audio": (row.get("audio") or "").strip(),
        "is_ielts_tag": 1 if is_ielts_tag else 0,
        "priority_score": priority_score(row, is_ielts_tag),
        "source": source,
    }


def better_entry(left, right):
    # Keep the entry with higher priority, then richer definitions.
    if left["priority_score"] != right["priority_score"]:
        return left if left["priority_score"] > right["priority_score"] else right

    left_density = (
        field_non_empty(left.get("phonetic"))
        + field_non_empty(left.get("definition_zh"))
        + field_non_empty(left.get("definition_en"))
    )
    right_density = (
        field_non_empty(right.get("phonetic"))
        + field_non_empty(right.get("definition_zh"))
        + field_non_empty(right.get("definition_en"))
    )
    if left_density != right_density:
        return left if left_density > right_density else right

    return left if left["word"] < right["word"] else right


def build_vocab(csv_path, target_size):
    primary = {}
    supplement_candidates = {}

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = normalize_word(row.get("word"))
            if not is_valid_headword(word):
                continue

            tags = split_tags(row.get("tag"))
            is_ielts_tag = "ielts" in tags

            if is_ielts_tag:
                entry = row_payload(row, True, "ielts_tag")
                key = entry["word_lower"]
                if key not in primary:
                    primary[key] = entry
                else:
                    primary[key] = better_entry(primary[key], entry)
            else:
                entry = row_payload(row, False, "supplement")
                key = entry["word_lower"]
                if key not in supplement_candidates:
                    supplement_candidates[key] = entry
                else:
                    supplement_candidates[key] = better_entry(
                        supplement_candidates[key], entry
                    )

    selected = dict(primary)

    if len(selected) < target_size:
        need = target_size - len(selected)
        supplements = [
            x for key, x in supplement_candidates.items() if key not in selected
        ]
        supplements.sort(
            key=lambda r: (
                -r["priority_score"],
                -r["collins"],
                -r["oxford"],
                r["frq"] if r["frq"] > 0 else 10**9,
                r["bnc"] if r["bnc"] > 0 else 10**9,
                r["word"],
            )
        )
        for entry in supplements[:need]:
            selected[entry["word_lower"]] = entry

    result = list(selected.values())
    result.sort(key=lambda r: (-r["priority_score"], r["word"]))
    return result


def init_db(conn):
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            word_lower TEXT NOT NULL UNIQUE,
            phonetic TEXT DEFAULT '',
            definition_en TEXT DEFAULT '',
            definition_zh TEXT DEFAULT '',
            pos TEXT DEFAULT '',
            collins INTEGER NOT NULL DEFAULT 0,
            oxford INTEGER NOT NULL DEFAULT 0,
            tag TEXT DEFAULT '',
            bnc INTEGER NOT NULL DEFAULT 0,
            frq INTEGER NOT NULL DEFAULT 0,
            exchange TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            audio TEXT DEFAULT '',
            is_ielts_tag INTEGER NOT NULL DEFAULT 0,
            priority_score REAL NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_words_word ON words(word);
        CREATE INDEX IF NOT EXISTS idx_words_priority ON words(priority_score DESC);
        CREATE INDEX IF NOT EXISTS idx_words_source ON words(source);

        CREATE TABLE IF NOT EXISTS word_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'new',
            is_new INTEGER NOT NULL DEFAULT 1,
            repetition INTEGER NOT NULL DEFAULT 0,
            interval_days INTEGER NOT NULL DEFAULT 0,
            ease_factor REAL NOT NULL DEFAULT 2.5,
            due_date TEXT NOT NULL DEFAULT (date('now')),
            last_reviewed_at TEXT,
            next_review_at TEXT,
            review_count INTEGER NOT NULL DEFAULT 0,
            wrong_count INTEGER NOT NULL DEFAULT 0,
            lapse_count INTEGER NOT NULL DEFAULT 0,
            last_score INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_word_memory_due_date ON word_memory(due_date);
        CREATE INDEX IF NOT EXISTS idx_word_memory_status ON word_memory(status);

        CREATE TABLE IF NOT EXISTS review_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL,
            reviewed_at TEXT NOT NULL,
            score INTEGER NOT NULL,
            rating_label TEXT NOT NULL DEFAULT '',
            repetition_before INTEGER NOT NULL DEFAULT 0,
            repetition_after INTEGER NOT NULL DEFAULT 0,
            interval_before INTEGER NOT NULL DEFAULT 0,
            interval_after INTEGER NOT NULL DEFAULT 0,
            ease_before REAL NOT NULL DEFAULT 2.5,
            ease_after REAL NOT NULL DEFAULT 2.5,
            due_before TEXT,
            due_after TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_review_logs_word_time
            ON review_logs(word_id, reviewed_at DESC);

        CREATE TABLE IF NOT EXISTS user_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def insert_words(conn, entries):
    conn.executemany(
        """
        INSERT INTO words (
            word, word_lower, phonetic, definition_en, definition_zh, pos,
            collins, oxford, tag, bnc, frq, exchange, detail, audio,
            is_ielts_tag, priority_score, source
        ) VALUES (
            :word, :word_lower, :phonetic, :definition_en, :definition_zh, :pos,
            :collins, :oxford, :tag, :bnc, :frq, :exchange, :detail, :audio,
            :is_ielts_tag, :priority_score, :source
        );
        """,
        entries,
    )

    conn.executescript(
        """
        INSERT INTO word_memory (word_id)
        SELECT id FROM words
        WHERE id NOT IN (SELECT word_id FROM word_memory);

        INSERT OR IGNORE INTO user_settings(key, value) VALUES
            ('daily_new_words', '20'),
            ('auto_pronounce', '1'),
            ('show_english_definition', '1');
        """
    )


def build_report(entries, output_db_path, report_path, target_size):
    total = len(entries)
    with_phonetic = sum(1 for e in entries if field_non_empty(e.get("phonetic")))
    with_zh = sum(1 for e in entries if field_non_empty(e.get("definition_zh")))
    with_en = sum(1 for e in entries if field_non_empty(e.get("definition_en")))
    from_ielts_tag = sum(1 for e in entries if e.get("is_ielts_tag") == 1)
    from_supplement = sum(1 for e in entries if e.get("source") == "supplement")

    top50 = sorted(entries, key=lambda r: (-r["priority_score"], r["word"]))[:50]

    lines = [
        "# IELTS 词库统计报告",
        "",
        f"- 生成时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 目标词数: {target_size}",
        f"- 实际总词数: {total}",
        f"- `tag` 包含 `ielts` 的词数: {from_ielts_tag}",
        f"- 补充词数: {from_supplement}",
        f"- 有音标数量: {with_phonetic}",
        f"- 有中文释义数量: {with_zh}",
        f"- 有英文释义数量: {with_en}",
        f"- 数据库文件: {output_db_path}",
        "",
        "## 前 50 个高优先级词",
        "",
        "| # | word | score | source | collins | oxford | frq | bnc |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]

    for idx, e in enumerate(top50, start=1):
        lines.append(
            f"| {idx} | {e['word']} | {e['priority_score']:.3f} | {e['source']} | "
            f"{e['collins']} | {e['oxford']} | {e['frq']} | {e['bnc']} |"
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "total": total,
        "from_ielts_tag": from_ielts_tag,
        "from_supplement": from_supplement,
        "with_phonetic": with_phonetic,
        "with_zh": with_zh,
        "with_en": with_en,
    }


def main():
    parser = argparse.ArgumentParser(description="Build IELTS vocab SQLite DB from ECDICT CSV.")
    parser.add_argument(
        "--csv",
        default=str(Path("ECDICT") / "ecdict.csv"),
        help="Path to ECDICT CSV file.",
    )
    parser.add_argument(
        "--output-db",
        default="ielts_vocab.db",
        help="Output SQLite DB path.",
    )
    parser.add_argument(
        "--report",
        default="ielts_vocab_report.md",
        help="Output report markdown path.",
    )
    parser.add_argument(
        "--target-size",
        type=int,
        default=6000,
        help="Minimum target size; supplement if IELTS-tag words are fewer than this value.",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    output_db_path = Path(args.output_db).resolve()
    report_path = Path(args.report).resolve()

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    entries = build_vocab(csv_path, max(1, args.target_size))

    if output_db_path.exists():
        output_db_path.unlink()

    conn = sqlite3.connect(str(output_db_path))
    try:
        init_db(conn)
        insert_words(conn, entries)
        conn.commit()
    finally:
        conn.close()

    summary = build_report(entries, output_db_path, report_path, args.target_size)

    print("Build completed.")
    print(f"DB: {output_db_path}")
    print(f"Report: {report_path}")
    print(
        "Summary: total={total}, ielts_tag={from_ielts_tag}, supplement={from_supplement}, "
        "phonetic={with_phonetic}, zh={with_zh}, en={with_en}".format(**summary)
    )


if __name__ == "__main__":
    main()

