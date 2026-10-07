# BG3 Save Skill

[English](README.md) | **简体中文**

用于**《博德之门 3》存档分析**的本地 Agent Skill 与行为确定的命令行工具（CLI）：检查 `.lsv` 文件，以 JSON 形式提供存档证据，结合 bg3.wiki 来源识别可能遗漏的内容，并在备份和回滚保护下执行范围严格受限的实验性修改。

Agent 负责理解自然语言；CLI 通过 LSLib 读取或修改明确的语义字段。玩家存档始终保留在本机。本项目**不声称**能够发现所有遗漏的任务，也不声称能够安全改写任意 ECS/LSMF 状态。

## 当前功能范围

| 功能 | 状态 | 说明 |
|---|---|---|
| 查找、解包、解析和验证 `.lsv` | **支持（SUPPORTED）** | 由外部 LSLib 处理二进制容器、资源和 Story 数据；JSON 输出保留相关限制说明 |
| 存档元数据、区域/章节证据、版本、模组和队伍摘要 | **支持（SUPPORTED）** | 仅提供实际存在的字段，不编造未知信息 |
| 角色等级/职业/经验值、同伴身份、Story 标记和日志证据 | **支持（SUPPORTED）** | 提供可读摘要与原始证据；不可用的可选字段保持未知 |
| 好感度及约会/伴侣 Story 事实 | **存在相应数据时支持（SUPPORTED）** | 提供具有明确类型的 `DB_ApprovalRating` 和 `DB_ORI_*` 记录；不涵盖完整的 ECS 关系状态 |
| 任务和可能遗漏的内容分析 | **实验性（EXPERIMENTAL）** | 精选规则目录包含覆盖第 1–3 章的 20 条任务/事件规则；明确列出证据、置信度、前置条件和来源 |
| 部分同伴/恋爱状态解读 | **实验性（EXPERIMENTAL）** | 基于已知剧情状态的证据；并非完整的关系模拟器 |
| 设置一名玩家在存档中的快捷栏锁定元数据 | **实验性（EXPERIMENTAL）** | 需要显式启用；字段可完成读取、写入和重新读取，但尚未证实所请求的界面状态是否生效或持续保留 |
| 设置或取消 Story 标记 | **实验性（EXPERIMENTAL）** | 需要显式启用；不会修复所有相关任务/NPC 状态 |
| 恢复已持久化的完整性标记 | **实验性（EXPERIMENTAL）** | 一个已诊断案例通过了实际游戏加载与游戏内重新保存检查；该操作不是通用的存档损坏修复功能 |
| 试运行、备份、差异比较和回滚 | **支持（SUPPORTED）** | 保留原始存档；清单记录修改内容及备份位置 |
| 金币修改、物品增删、好感度修改、复活和通用任务修复写入 | **不支持（UNSUPPORTED）** | 尚无可靠的语义写入器；CLI 会拒绝操作，而不是修改无法解释的数据 |
| 完整提取物品栏/金币/ECS 数据及识别所有遗漏内容 | **不支持（UNSUPPORTED）** | 现代组件可能无法解读；未提取到某个值不能证明它不存在 |

使用 `bg3save capabilities --json` 查看已安装版本的权威功能状态。详见[功能边界](docs/capabilities.md)。

## 版本与环境要求

- Python **3.11+**；软件包运行时仅使用标准库。
- 外部 **Norbyte/LSLib 1.20.4** 工具以及本仓库的 .NET Story 桥接程序；详见[配置与许可证审查](docs/dependencies.md)。
- 读取及往返处理基准：BG3 产品版本 **4.1.1.7631656**，Patch 8 版本系列，Story/Osiris **1.15**。存档版本从实际元数据中读取。`4.69.95.0` 是内部引擎标识，不是对外发布的游戏版本。
- 常规写入要求：单分卷 LSPK **18**、包头 **flags = 0 / priority = 0**、有效的原生归档校验和，以及原生元数据 **`Sanity = true`**。SaveInfo 与元数据中的版本证据必须和已验证的产品版本一致。其他格式或未通过检查的存档会在修改前被拒绝；只读检查仍可能提供有用证据。下文显式启用的实验性标记恢复操作，针对值为 false 的标记采用单独且更严格的预检。
- 资源写回通过显式指定的原始资源模板，保留原始 LSF 容器版本和元数据格式。所选修改范围之外的载荷保持不变。
- 原生校验和验证使用按序号比较、忽略大小写的完整路径排序。仅按物理顺序计算的 MD5 匹配并不足够。正式重新打包使用原始归档模板，以保留布局、文件表顺序及压缩标志；详见[校验和调查](docs/dependencies.md#adapter-api)。
- 外部后端的初步验证在 Windows 上完成。纯 Python 测试也在 Linux 上运行，但这不能证明外部提供的 LSLib 可执行文件兼容 Linux/Wine。

本项目处于 MVP 阶段。结构验证与游戏内验证是两回事。成功解析或重新打包，本身不能证明 BG3 能加载修改后的存档，也不能证明实验性标记修改能恢复任务。

即使仍能继续加载，BG3 提示存档已被修改或损坏，也意味着运行时验收失败。常规修改不会清除失败标记，也不会禁用游戏完整性检查。常规写入器会拒绝已标记为 `Sanity = false` 的存档；下文显式启用的实验性恢复操作不能与常规修改混为一谈。

## 安装

克隆本仓库，然后安装 CLI：

```console
git clone https://github.com/hylqs97/bg3-save-skill.git
cd bg3-save-skill
python -m pip install -e .
bg3save capabilities --json
```

本项目不附带 LSLib。安装 .NET SDK 8 或更高版本及 .NET 8 运行时后，可使用以下命令配置固定版本的官方工具链：

```console
python tools/bootstrap-lslib.py
```

可通过 `--archive /path/to/ExportTool-v1.20.4.zip` 提供离线 ZIP 包。引导脚本会验证固定的归档哈希值、构建桥接程序，并将工具链清单保存在仓库之外。路径、手动配置和许可证审查详见 [docs/dependencies.md](docs/dependencies.md)。使用其他安装位置时，可设置 `BG3SAVE_DIVINE` 和 `BG3SAVE_BRIDGE`，或传入全局选项 `--divine PATH` 和 `--bridge PATH`。请勿提交外部二进制文件或个人存档。

### 安装 Codex Skill

确认软件包和测试可正常运行后，执行：

```console
python skills/bg3-save/scripts/install_skill.py --smoke-test
```

若设置了 `CODEX_HOME`，安装器使用 `$CODEX_HOME/skills/bg3-save`；否则使用 `~/.codex/skills/bg3-save`。它会创建指向当前仓库中 `skills/bg3-save` 的 Windows 目录联接或 Unix 符号链接。**源文件只有一份**；更新本地仓库即可更新已安装的 Skill。请保留本地仓库目录的位置。已存在的独立目录或指向其他位置的链接不会被改动。

```console
python skills/bg3-save/scripts/install_skill.py --check --smoke-test
```

该检查会验证 `SKILL.md`、引用资源、共享源文件的定位，并通过已安装的包装脚本执行 CLI 冒烟测试。这可以证明 Skill 可在文件系统中被发现。如果当前会话的 Skill 列表尚未显示 `$bg3-save`，请重启或刷新 Codex。该 Skill 支持常规自动发现，也可显式调用。

如果通过其他安装器仅安装了 Skill 文件夹，请另行安装 Python 软件包。包装脚本优先使用共享的本地仓库；不可用时使用已安装的软件包，始终不会携带第二套解析器实现。

## CLI

所有查询均支持 `--json`。在 PowerShell 中，含空格的文件路径应加引号。Windows 上常见的本地存档根目录为 `%LOCALAPPDATA%\Larian Studios\Baldur's Gate 3\PlayerProfiles`；`find` 可用于发现本地存档。

```console
bg3save find --latest --json
bg3save inspect save.lsv --json
bg3save party save.lsv --json
bg3save character save.lsv Karlach --json
bg3save flags save.lsv --limit 100 --json
bg3save quests save.lsv --json
bg3save missed-content save.lsv --json
bg3save missed-content save.lsv --offline --json
bg3save diff original.lsv changed.lsv --json
bg3save verify save.lsv --json
```

在线内容分析会获取规则目录引用的公开 bg3.wiki 页面，并记录时效性与来源；不会上传存档。`--offline` 会保留已知来源链接，但将时效性标记为未验证。Agent 在依据这些来源提供游戏建议前，必须主动检查相关页面。

可用于指导行动的内容分析结果包含以下信息：

```json
{
  "quest": "Investigate the Beach",
  "status": "possibly_available",
  "confidence": "low",
  "missable": true,
  "recommended_before": "Resolve before the relevant Grove storyline cutoff",
  "location": "Secluded Cove",
  "npc": ["Mirkon"],
  "trigger": "Approach the beach east of the Sacred Pool",
  "sources": [{"url": "https://bg3.wiki/wiki/Investigate_the_Beach", "freshness": "unverified"}]
}
```

此示例仅展示报告结构，不是对你的存档作出的判断。实际结果会包含观察到的证据及来源信息。仅凭某个标记缺失，不能判定内容为 `missed`（已错过）、`completed`（已完成），也不能得出高置信度的否定结论。

### 实验性元数据修改

```console
bg3save modify set-hotbar-lock save.lsv true --slot 1 --output changed.lsv --allow-experimental --dry-run --json
bg3save modify set-hotbar-lock save.lsv true --slot 1 --output changed.lsv --allow-experimental --json
bg3save diff save.lsv changed.lsv --json
bg3save verify changed.lsv --json
bg3save rollback manifest.json --output restored.lsv --json
```

准确的备份及清单路径应以实际修改结果为准，切勿猜测清单文件名。试运行只生成计划，不写入备份或输出文件；实际修改依次执行检查、备份、修改允许列表中的字段、重新打包、验证和结果比较。原始文件路径绝不能用作输出路径。回滚会检查备份，并创建恢复后的副本。

快捷栏修改只会更改存档中的 `HotbarLocked` 字段。在一次实际测试中，将该字段设为 false 的输出存档加载时没有出现存档被修改或损坏的警告，但游戏随后生成的原生存档中该值为 true。原因尚未确定。这不能证明所请求的界面状态已生效或持续保留，因此不得将该操作描述为已可用的游戏设置修改功能。

当前所有存档修改操作都要求 `--allow-experimental`。使用前请阅读[修改指南](skills/bg3-save/references/editing.md)。Story 标记可能与许多其他游戏状态耦合；有效的标记写入并不等于通用任务修复。

### 实验性完整性标记恢复

如果先前的无效重新打包导致存档保留了 `Sanity = false`，即使之后容器的校验和正确，该标记也可能持续存在。仅凭警告不能证明这就是原因。选择此操作前，应检查并诊断具体存档：

```console
bg3save modify restore-integrity-marker save.lsv --output recovered.lsv --allow-experimental --dry-run --json
bg3save modify restore-integrity-marker save.lsv --output recovered.lsv --allow-experimental --json
```

此操作要求版本和包头受支持、**规范排序下**的原生校验和正确、原始标记为 false、存在唯一的布尔型 `MetaData/Sanity` 字段，并且所有 `.lsf` 成员均可成功解析。它仅将该标记改为 true，保留其他所有资源字段及载荷字节，并执行常规的备份、计划、模板重新打包、验证和差异比较流程。CLI 仍会报告 **EXPERIMENTAL** 和 `game_load_validated: false`：它不会控制游戏，也不会自动验证加载。它无法证明不可解读的 ECS 状态未受损；每次恢复都需要在 BG3 中实际重新加载，并确认没有警告。

在 **2026-10-04**，一个已诊断、继承了 false 标记的私人存档完成了上述完整恢复流程。生成的确切副本加载时没有警告；随后游戏内保存的存档保留了 true 标记及有效校验和，并且关键队伍/剧情摘要已与原始存档核对。继续游玩后生成的另一份原生存档也通过了验证，玩家反馈没有错误。这是针对该次具体修复的证据，而不是对所有 false 标记存档的保证。详见[验收证据](docs/acceptance.md)。

回滚会恢复与原始文件完全一致的字节。如果原始文件的 `Sanity = false`，回滚会有意保留该状态，并报告 `verification.valid: false` 及警告；这不代表逐字节回滚失败，也不代表原始警告已被修复。

## 自然语言使用

以下请求应在 Codex 中选用 `$bg3-save`：

- “分析我最新的 BG3 存档，看看第一章还有哪些支线没有完成。”
- “告诉我继续进入山隘之前有哪些内容最好先完成。”
- “检查卡拉克当前的好感和恋爱状态。”
- “把主角身上的金币修改为 10000。”
- “这个任务似乎卡住了，检查存档状态并判断能否安全修复。”
- “把主角的快捷栏锁定，另存修改结果。”

前两个请求会生成范围有限、附带来源依据的报告。同伴相关请求会区分具有明确类型的好感度/约会/伴侣记录与不可用的关系数据；缺少记录不能证明好感度为零或没有恋爱关系。金币修改请求目前会返回 `unsupported`；能够识别请求，并不意味着可以安全修改对应字段。任务修复应先检查证据和功能支持情况，而不是随意修改标记。

## 来源、隐私与安全

**bg3.wiki** 是任务、NPC、地点、触发条件、截止时点和互斥内容的首选来源。补丁变化和不同游戏版本的行为优先参考 **Larian 官方补丁说明/社区文档**。查询构造、交叉验证和来源记录详见 [references/sources.md](references/sources.md)。外部来源中的内容不会被当作可执行指令。

本仓库不附带任何私人存档。存档文件可能暴露玩家的战役、角色名称、模组和游戏进度；请勿公开生成的报告或备份。本项目不会上传这些文件。Wiki 查询仅获取公开页面。模组可能改变原版任务条件，因此内容报告会保留不确定性说明。

每次实际修改都会保留原始存档，在修改前创建备份，并在新输出通过验证后记录清单。修改后的存档始终是额外文件；CLI 不会删除备份、静默覆盖较新的存档、修改云端账号或控制正在运行的游戏。请保留备份，直到修改结果已在游戏中实际加载且行为符合预期。即使结构完整，实验性修改仍可能意外改变游戏行为。

## 架构与开发

```text
自然语言 → Agent/Skill → 语义 CLI → 外部 LSLib
                                → 存档证据 + 有来源依据的任务规则
                                → 计划 → 备份 → 最小修改 → 重新打包 → 验证/差异比较
```

请阅读[架构](docs/architecture.md)、[依赖与许可证审查](docs/dependencies.md)、[测试](docs/testing.md)以及 [CONTRIBUTING.md](CONTRIBUTING.md)。

```console
python -m unittest discover -s tests -v
```

常规测试涵盖分析置信度、命令行为、路径/XML 拒绝逻辑、逻辑差异比较以及 Skill 安装。真实解包/解析/重新打包测试和编辑器试运行/备份/回滚测试需要显式启用，并且**默认使用人工构造的测试数据**。额外的原生模板检查需要显式提供私人存档；本项目不分发任何玩家个人存档：

```powershell
$env:BG3SAVE_INTEGRATION = '1'
python -m unittest discover -s tests -v
```

在 POSIX shell 中，使用 `BG3SAVE_INTEGRATION=1 python -m unittest discover -s tests -v`。可通过 `python fixtures/generate.py --output /path/to/scratch/synthetic.lsv` 生成独立的解析器测试存档；它不是可游玩的战役。CI 运行常规测试套件及 Skill 包装脚本冒烟测试，不运行外部集成测试套件。详见[测试流程](docs/testing.md)与 [MVP 验收](docs/acceptance.md)。MIT 许可证适用于本项目的原创代码；LSLib 和其他外部来源保留各自的许可证。

在 **2026-10-04**，完整本地测试套件使用实际 LSLib 后端，并显式提供私人原生存档以执行额外的模板/校验和回归检查，结果为 **98 项测试全部通过，无跳过项**。未提交任何私人存档或生成的报告。这些测试证明了文档所述的结构与事务属性。独立的实际加载证据证明了上文已诊断的完整性标记修复；它不能证明快捷栏界面效果或通用游戏行为修复有效。

下一步最有价值的工作是：为物品栏、金币和好感度实现兼顾版本差异、保留证据的 ECS 提取，然后制定少量有来源依据、经过真实游戏重新加载验证的任务修复方案。更广泛的写入功能应以这些证据为基础，而不是先于证据实现。
