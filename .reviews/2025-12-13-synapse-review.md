# Synapse 项目审查报告（2025-12-13）

> 目标：审查项目缺陷（逻辑 / 架构 / 代码质量）与不足（功能性需求不完善）。本报告仅记录问题与建议，不做代码修改。

## 审查范围与依据

- 代码：`src/synapse/`、`tests/`
- 关键文档：
  - `README.md`、`QUICKSTART.md`、`TESTING.md`、`MVP_STATUS.md`
  - `.kiro/steering/`（product/structure/tech）
  - `.kiro/specs/`（重点：`project-synapse/total_reqs.md`、`synapse-mvp/*`、`synapse-incremental/*`、`improved-call-resolution/*`、`go-signature-resolution/*`、`java-overload-resolution/*`、`adapter-refactor/*`）
- 运行验证（仅用于判断“现状可运行性/稳定性”）：
  - `uv run pytest tests/unit`：通过
  - `uv run pytest tests/integration`：通过（依赖本地 `tests/fixtures/` 目录存在）

## 总体结论

项目已具备 MVP 的主要骨架（解析→IR→写入 Neo4j→查询→CLI），测试也能在当前工作区跑通。但存在一些会影响正确性与长期演进的关键问题：

- “多语言扫描”在当前实现下容易写错 `languageType`（数据正确性风险）。
- 项目/图数据生命周期管理不清晰（删除、重复扫描、版本/增量扫描缺失导致陈旧数据残留）。
- 配置源重复且默认值不一致（`.env` 的加载路径与 Neo4j 连接配置存在分裂）。
- 仓库工程化/可复现性存在明显问题（关键测试夹具与锁文件被忽略、文档编码与路径不一致）。

下面按严重级别列出问题。

## 关键缺陷（Critical）

### C1. 多语言扫描写入 `languageType` 可能错误（数据正确性/查询语义污染）

**现象**

- `ScannerService.scan_project()` 会对检测到的多个语言依次 `adapter.analyze()`，并用 `IR.merge()` 合并后一次性写入 Neo4j。
- `IR.merge()` 的返回对象保留 `self.language_type`；`GraphWriter` 写节点时使用 `ir.language_type.value`，而不是实体自身的 `language_type` 字段。

**影响**

- 当一个项目同时包含 Go 与 Java（或未来更多语言）时，写入的 `Module/Type/Callable.languageType` 可能被统一写成“第一次合并的语言”，导致：
  - 语言过滤/约束（schema 的复合唯一键包含 `languageType`）语义失真；
  - 跨语言实体混淆，后续查询/统计结果不可置信。

**涉及位置**

- `src/synapse/core/models.py`：`IR.merge()`
- `src/synapse/services/scanner_service.py`：多语言合并再写入
- `src/synapse/graph/writer.py`：写入节点时使用 `ir.language_type`

**建议（不在本次修改范围内）**

- 明确“一个 IR 是否允许多语言混合”。两种常见修复路径：
  1. **不合并**：按语言分别写入（并在图层以 `projectId+languageType` 做隔离）。
  2. **允许混合**：`IR.language_type` 改为 `MIXED/None`，并在写入时使用实体自身 `language_type`。

---

### C2. `ProjectService.delete_project()` 逻辑返回值不可靠 + 与需求的“归档”语义不一致

**现象/逻辑问题**

- `delete_project()` 先检查 project 是否存在，然后用一个 Cypher 把 Project 与 `projectId` 关联的节点删除。
- 返回值用 `RETURN count(*) AS deleted`，计数的是被 `UNWIND nodes` 后的行数；当项目只有 `Project` 节点、没有任何 `projectId` 关联节点时，函数会返回 `False`，即“删除失败”，但实际上 `Project` 节点可能已被删除。
- 该删除策略是“物理删除”，而 `.kiro/specs/project-synapse/total_reqs.md` 中 Requirement 1 的 AC 5 期望“逻辑删除/archived，并默认查询排除”。

**影响**

- CLI 的 `delete` 命令可能把“已删除”显示成“失败/未找到”（取决于上层如何解释返回值）。
- 与需求文档冲突，后续引入 revision/增量/审计时更难补齐语义。

**涉及位置**

- `src/synapse/services/project_service.py`
- `.kiro/specs/project-synapse/total_reqs.md`（Requirement 1）

**建议**

- 将“删除返回值”与“删除策略”拆开：返回值应反映 Project 是否被删除/归档成功；同时明确是否实现 archived 语义。

---

## 高优先级问题（High）

### H1. 配置源重复且默认值冲突：`.env`、`core.config` 与 `graph.connection` 分裂

**现象**

- `src/synapse/core/config.py` 用 `pydantic-settings`，会读取 `.env`，并将 `neo4j_password` 默认设为空（与 `README.md` 的表格一致）。
- `src/synapse/graph/connection.py` 自建 `Neo4jConfig.from_env()`，不读取 `.env`，且把密码默认值设为 `"neo4j"`（与 `README.md`/`core.config` 不一致，也有安全隐患）。
- CLI 额外调用 `dotenv.load_dotenv()`，进一步加重“不同入口不同配置行为”。

**影响**

- 同一套配置在“库调用/CLI 调用/测试”间表现不一致；新用户按 `.env.example` 配置也可能无法生效（尤其在非 CLI 场景）。

**涉及位置**

- `src/synapse/core/config.py`
- `src/synapse/graph/connection.py`
- `src/synapse/cli/main.py`
- `README.md`

---

### H2. Neo4j Schema 初始化代码存在但未被调用（约束/索引可能从未建立）

**现象**

- `src/synapse/graph/schema.py` 提供了 `ensure_schema()`，但从代码检索看没有任何调用点。

**影响**

- 唯一约束/索引可能缺失：性能下降、重复数据风险上升、与需求文档（Requirement 10 的 AC 5）不一致。

**涉及位置**

- `src/synapse/graph/schema.py`
- `.kiro/specs/project-synapse/total_reqs.md`（Requirement 10）

---

### H3. 重复扫描缺少“收敛策略”：陈旧节点/关系可能长期残留

**现象**

- `GraphWriter` 采用 `MERGE` 写入节点/关系，但没有在扫描开始前清理项目旧数据，也没有 revision 隔离。
- `GraphWriter.clear_project()` 存在但 `ScannerService.scan_project()` 未使用。

**影响**

- 一旦源码发生删除/重命名，图中旧实体可能永远留存；查询结果不再代表“当前代码状态”。
- 与 `.kiro/specs/project-synapse/total_reqs.md` 的 Revision/增量扫描规划存在较大缺口。

**涉及位置**

- `src/synapse/services/scanner_service.py`
- `src/synapse/graph/writer.py`
- `.kiro/specs/project-synapse/total_reqs.md`（Requirement 8/13）
- `.kiro/specs/synapse-incremental/requirements.md`

---

### H4. 确定性（Determinism）存在结构性风险：文件遍历顺序 + 签名/返回类型 fallback

**现象**

- `*.rglob("*.java") / rglob("*.go")` 未排序；不同文件系统/平台的遍历顺序可能不同。
- `SymbolTable.get_callable_signature()` / `get_callable_return_type()` 在“同名多签名”场景下存在“取第一个命中”的逻辑，依赖插入顺序（而插入顺序又依赖文件遍历顺序）。

**影响**

- 与 `.kiro/specs/improved-call-resolution/requirements.md` 的 Requirement 5（确定性要求）存在偏差；
- 在存在重载/同名冲突的真实工程中，解析结果可能在不同机器上出现差异，进而影响图边的稳定性。

**涉及位置**

- `src/synapse/adapters/go/scanner.py`、`src/synapse/adapters/go/resolver.py`
- `src/synapse/adapters/java/scanner.py`、`src/synapse/adapters/java/resolver.py`
- `src/synapse/adapters/base.py`
- `.kiro/specs/improved-call-resolution/requirements.md`

## 中优先级问题（Medium）

### M1. 需求与实现不一致：Project/Module/Type/Callable 的字段与关系缺失

对照 `.kiro/specs/project-synapse/total_reqs.md`：

- Project：缺少 `description`、`archived` 等字段与默认过滤逻辑（Requirement 1）。
- Project↔Module：需求要求 `Project -[:CONTAINS]-> Module`，当前主要用 `projectId` 属性隔离（Requirement 2）。
- TypeKind/CallableKind：需求包含更多枚举值（如 `TRAIT/TYPE_ALIAS/BUILTIN`、`LAMBDA/CLOSURE`），当前模型较窄（Requirement 3/4）。
- Variable/Block/Dependency/Revision/IMPORTS/USES：需求文档中明确存在（Requirement 5/6/7/8/9），实现基本缺失。

相关位置：`src/synapse/core/models.py`、`src/synapse/graph/writer.py`、`src/synapse/graph/queries.py`

---

### M2. `SchemaManager.ensure_schema()` 的统计字段命名容易误导

当前 `ensure_schema()` 的 `constraints_created/indexes_created` 更像是“执行成功次数”，并不能区分“新建/已存在”，且语义与 docstring 不一致。

相关位置：`src/synapse/graph/schema.py`

---

### M3. 扫描性能与过滤策略偏弱

- `ScannerService._detect_languages()` 对每个扩展名都 `list(rglob())`，大仓库会产生不必要的全量遍历与内存占用。
- Java 扫描未过滤常见构建目录（如 `target/`、`build/`、`.git/`），Go 虽过滤 `vendor/` 与 `_test.go`，但整体过滤策略仍偏弱。

相关位置：`src/synapse/services/scanner_service.py`、`src/synapse/adapters/java/scanner.py`、`src/synapse/adapters/go/scanner.py`

---

### M4. API/命名重复导致认知负担：`QueryService` 在 graph 与 services 层同名

`src/synapse/graph/queries.py` 与 `src/synapse/services/query_service.py` 都暴露 `QueryService`，虽通过别名规避导入冲突，但对使用者与维护者不友好，且两层默认值/配置来源也不一致。

相关位置：`src/synapse/graph/queries.py`、`src/synapse/services/query_service.py`

## 低优先级问题（Low / Hygiene）

### L1. 文档与编码/示例一致性问题

- `QUICKSTART.md`、`TESTING.md`、`MVP_STATUS.md` 在当前环境输出存在明显乱码（疑似 UTF-8 被错误解码），会影响可读性与对外使用。
- 示例路径存在不一致：文档中出现 `tests/fixtures/java-sample`（连字符）而实际目录为 `tests/fixtures/java_sample`（下划线）。

相关位置：`QUICKSTART.md`、`TESTING.md`、`MVP_STATUS.md`、`tests/fixtures/`

---

### L2. 元数据与发布准备不足

- `pyproject.toml` 的 `project.urls` 使用占位符 `https://github.com/username/synapse`。
- `pyproject.toml` 声明 MIT License，但仓库未发现 `LICENSE` 文件。
- `[dependency-groups]` 中 `docs` 依赖组疑似被写进注释（没有真实生效）。

相关位置：`pyproject.toml`

---

### L3. 约定未被执行：适配器拆分后仍有多个文件超过 400 行

`.kiro/specs/adapter-refactor/requirements.md` 明确了“每个文件 < 400 行”，但当前多处文件显著超过（例如 Go/Java resolver、Java type_inferrer、CLI main 等）。

相关位置：`.kiro/specs/adapter-refactor/requirements.md`、`src/synapse/adapters/*`、`src/synapse/cli/main.py`

---

### L4. 规格文档目录不完整

`.kiro/specs/synapse-variable-block/` 目录存在，但未发现 `requirements.md/design.md/tasks.md` 等文件，导致“Variable/Block”需求与实现对照困难。

## 建议的修复优先级（路线图）

1. **先保正确性**：解决 C1（多语言扫描/写入 `languageType`）。
2. **明确生命周期语义**：统一 Project 删除/归档策略，并修复 `delete_project()` 返回值语义（C2）。
3. **统一配置入口**：让 Neo4j 连接配置与 `.env`/`SynapseConfig` 统一（H1）。
4. **保证可复现**：调整 `.gitignore` 策略，明确 `tests/fixtures/` 与 `uv.lock` 的版本控制策略（C3）。
5. **启动时 schema 初始化**：在 CLI 或服务初始化阶段调用 `ensure_schema()`（H2）。
6. **收敛扫描结果**：在没有 revision 之前，至少提供“扫描前清理/重建”选项或隔离策略（H3）。
7. **提升确定性**：排序文件遍历、避免“取第一个命中”的 fallback（H4）。

