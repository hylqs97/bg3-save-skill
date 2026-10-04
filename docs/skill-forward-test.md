# Skill forward test

Reviewed **2026-10-04** using the completed Skill instructions, current CLI help/capabilities, synthetic save evidence, and the linked current wiki pages. No real player save was changed by this review.

| Scenario | Evidence and expected behavior | Result |
|---|---|---|
| “把主角金币改成10000” | Read capabilities before writing. `set-gold` is unsupported. `modify set-gold not-a-save.lsv 10000 --dry-run --json` must refuse before trying to read or write that path. | JSON `UNSUPPORTED`, `unsupported_operation`; no write or invented success |
| “进入山隘之前还有什么可能漏掉” | Query current save evidence; actively review [time-sensitive activities](https://bg3.wiki/wiki/Time_sensitive_activities), [Save the Refugees](https://bg3.wiki/wiki/Save_the_Refugees), and [Investigate Kagha](https://bg3.wiki/wiki/Investigate_Kagha). With only Act 1/Wilderness and no journal/flags, preserve uncertainty. | Twenty-rule coverage marked incomplete; fifteen `possibly_available`, five `not_yet_available`; no unsupported `completed`/`missed` judgment from absences |
| Same Act, different map | Keep an explicitly active refugee journal unchanged; change synthetic region from `WLD_Main_A` to `CRE_Main_A`, both Act 1. | Ordinary active result becomes low-confidence `unknown` with region-cutoff evidence and a branch-check recommendation; no instruction assuming the Grove encounter remains available |
| Modded romance | Use the parser's actual module shape, `{"Name":"PolyamoryFixes","Folder":"PolyamoryFixes"}`, alongside an observed Karlach partnership flag. | The report detects the module and warns that vanilla relationship restrictions may differ |
| Skill command routing | Compare referenced query/edit commands with actual argparse help, including positional arguments and JSON options. | `find`, `flags`, `modify set-hotbar-lock`, experimental flags and rollback examples match the CLI |
| Linked installation | Install to a disposable Codex home with spaces in its path, smoke-test through the junction, then remove only the temporary link. | Shared source, required files and wrapper capabilities verified; source remains intact |
| Existing installation preservation | Place an independent directory/sentinel at the disposable install target. | Installer refuses replacement; sentinel unchanged |

The content regression suite passed after the region and actual-module-shape checks were included. The Skill's frontmatter validator and script compilation also passed. A standalone wrapper without an installed package returns a clear `cli_not_installed` error rather than recursively importing its own filename.

The temporary install test did not modify the user's real Codex Skill directory. Final local installation, backend round-trip and actual game-load evidence are separate completion checks. This review does not promote unsupported gameplay edits to supported capabilities or certify that the twenty-rule catalog finds all missed content.
