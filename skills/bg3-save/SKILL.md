---
name: bg3-save
description: Analyze Baldur's Gate 3 .lsv saves, inspect companions and story evidence, identify possible missed quests using bg3.wiki, and plan or perform only capability-supported save repairs. Use for BG3 save analysis or editing requests, including Chinese requests about missing Act 1 quests, Karlach romance, gold, or bugged quests.
---

# BG3 Save

Use the deterministic `bg3save` CLI for save data. Resolve `scripts/bg3save.py` relative to this file and run it with Python 3.11+. Prefer `--json`; do not infer success from descriptive text alone. The wrapper works from the full checkout (including a Codex junction/symlink installation) or with the Python package installed.

## Read and analyze

1. Use the user's named save. For “latest save,” use `find --json` and report the chosen path and timestamp. Multiple profiles or an ambiguous character name may need clarification. Do not switch to a different run without saying so.
2. Run `capabilities --json`, then `verify SAVE --json` and `inspect SAVE --json`. A missing LSLib backend is a setup issue; read [CLI setup](references/cli.md).
   If verification refuses a failed integrity marker, retain that failure and use read-only inspection for diagnosis. Do not silently switch saves or report the inspection as successful verification.
3. Query the relevant commands: `party`, `character`, `flags`, `quests`, or `missed-content`. Preserve the difference between an absent flag, an unparsed field, and a proven negative. A raw internal identifier is evidence, not a readable quest name.
4. For quest recommendations, read [source strategy](references/sources.md) and actively look up the relevant bg3.wiki pages. Use Larian's official sources for version or patch behavior. Reconcile current sources with save evidence; keep citations near the recommendation.
5. Explain completed, active, available, missed, mutually exclusive, and uncertain content separately when evidence supports those states. Include trigger, location/NPC, prerequisites, deadline, priority, confidence, and source links for available content. The bundled catalog covers selected quests; it cannot certify that the entire game has no missed content.

Use the user's language and desired spoiler depth. If no preference is given, name actionable objectives and warn before revealing major plot outcomes. For “before entering the Mountain Pass,” focus on deadlines relevant to that transition, not just current journal entries.

## Modify or repair

Read [editing and rollback](references/editing.md) before writes. Query capabilities for the exact requested operation and save format. A request such as “set gold to 10000” triggers this Skill but does not establish that gold writing is supported.

- Translate the request into a semantic CLI operation, never direct binary, hexadecimal, XML, or opaque ECS byte edits by the Agent.
- Follow the CLI's supported plan/dry-run/backup/new-output/verify/diff sequence. Keep the original save untouched. A user who already requested the edit need not approve the same reversible supported edit again; unresolved plot choices or a capability beyond the verified boundary need clarification.
- Return `unsupported` or `experimental` accurately. Do not call a repair successful because a plan was generated. Do not bypass a capability refusal by applying raw flag or Story-database changes yourself.
- For a diagnosed, authorized integrity-marker recovery, use only the explicit experimental `modify restore-integrity-marker` operation described in the editing reference. Its canonical checksum and full LSF parse checks are necessary but do not establish that opaque ECS state is sound. Ordinary edits still refuse a failed marker; never clear it as an incidental step or infer write authorization from an analysis request.
- File structural validation proves parseability and preserved payloads. Only an actual BG3 reload proves that the running game accepts a changed save. State which verification was performed.
- Leave automatic cloud sync, live game input, debugger settings, and mod load order unchanged unless they are required and within the user's authorization. Never overwrite a save actively being written.

## Useful requests

“分析我最新的 BG3 存档，看看第一章还有哪些支线没有完成。” → `find`, `inspect`, `quests`, `missed-content`, source verification.

“检查卡拉克当前的好感和恋爱状态。” → `character` and `flags`; report unknown fields and visible romance evidence separately.

“把主角身上的金币修改为 10000。” → capabilities first; use only a supported semantic writer or explain the current unsupported boundary.

“这个任务似乎卡住了，判断能否安全修复。” → collect relevant flags/quest/NPC evidence, current wiki conditions, then plan a supported repair or explain what additional evidence is needed.

Command details and output interpretation: [CLI reference](references/cli.md). Safety, supported writes, rollback: [editing reference](references/editing.md). Game knowledge: [source strategy](references/sources.md).
