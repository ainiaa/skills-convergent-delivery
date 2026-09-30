# Global Codex Memory — Java Fullstack + Karpathy Engineering

全局有效，适用于所有 Codex 项目和会话。转换自 `~/.claude/CLAUDE.md`，并按 Codex 工具/skill 口径调整。

## 0. Non-Negotiable TDD Rule

- 所有 feature、bugfix、refactor 默认先写/更新测试，再改业务代码。
- 测试必须覆盖正常、边界、异常场景。
- 重构前后都要保持现有测试通过。
- 没有可执行验证的改动视为未完成；若确实无法测试，在最终回复中明确说明原因和风险。

## 1. Core Engineering Mindset

1. 写代码前先理解问题，优先正确性、可读性、可维护性。
2. 偏好简单、显式、无惊喜的代码，避免过度抽象和提前优化。
3. 所有变更必须可验证、可测试、可追溯。
4. 修根因，不修症状；避免 workaround。
5. 小步提交，小步验证。
6. 边界清晰，错误处理清晰，职责拆分清晰。
7. 复用项目已有模式，不擅自发明架构或约定。
8. Debug 流程：先复现，再定位根因，再修复，最后补回归测试。

## 2. Tech Stack & Architecture

- Java: 8 / 11 / 21
- Framework: Spring Boot, Spring MVC, Spring Transaction
- ORM: MyBatis / MyBatis-Plus
- Database: MySQL 8.0+
- Cache: Redis + Redisson
- Architecture: Controller -> Service -> Mapper layered structure
- API: RESTful style
- Build: Maven / Gradle
- Test: JUnit 5, Mockito, Integration Test
- Gradle 禁 `--refresh-dependencies`：RELEASE 版本升级时 Gradle 会自动拉取新 JAR，加此参数会强制全量重下载所有依赖；仅 SNAPSHOT 且 `changing = true` 仍不生效时例外。

## 3. Java Coding Specification

- Class: UpperCamelCase
- Method/Variable: camelCase
- Constant: UPPER_SNAKE_CASE
- Database table/column: snake_case
- 不用拼音、无意义缩写、魔法数字。
- Controller 只负责参数接收、校验、响应包装、路由。
- Service 负责业务逻辑、事务控制、聚合、第三方调用。
- Mapper 只做 DB 操作，不写业务逻辑。
- Entity 映射 DB 字段，DTO/VO 隔离输入输出。
- 统一全局异常处理，不要散落 try-catch。

## 4. Transaction & Security

- 写操作 insert/update/delete 必须评估并使用 `@Transactional`。
- 参数校验按项目约定执行；若项目不支持注解校验，必须编程式校验。
- 防 SQL injection、XSS、越权访问。
- 不硬编码 key、password、secret、环境配置。
- 外部 API 要配置 timeout、retry/circuit breaker，并处理异常。

## 5. MySQL & SQL Rules

- 禁 `SELECT *`，除非项目既有 mapper 明确采用且本次不扩大范围。
- 禁无 WHERE 的全表 DELETE / UPDATE。
- 避免索引失效写法：函数包列、隐式转换等。
- 分页使用 limit / page helper。
- 模糊匹配优先前缀匹配，避免 leading `%`。
- 高频查询字段需要评估索引。
- 时间字段和时区必须统一。

## 6. Cache & Distributed

- Redis key 使用统一业务前缀，并按模块隔离。
- 防缓存穿透、击穿、雪崩。
- 分布式锁使用 Redisson。
- 缓存策略通常为先更新 DB，再删除缓存；如项目另有约定，以项目为准。

## 7. Logging

- 使用 SLF4J 统一日志。
- 关键入口、出口、异常、第三方调用要有日志。
- 敏感数据脱敏，不完整打印敏感信息。

## 8. Unit Test Mandatory Rule

- 业务核心代码、Service 层、工具类、公共组件必须覆盖单元测试。
- 优先 JUnit 5 + Mockito mock 依赖。
- 测试覆盖正常、边界、异常、非法参数场景。
- 新功能、bugfix、refactor 后必须写/更新测试。
- 不写空测试，测试必须有断言。

## 9. Code Quality & Refactor

- 返回空集合而不是 null。
- 方法单一职责，避免巨型方法。
- 避免在循环里做 DB / Redis / remote call。
- 复杂逻辑加简短业务背景注释。
- 重构必须保持原业务行为不变。

## 10. Codex Behavior Constraints

- 输出生产可用代码。
- 不经确认不引入新中间件、依赖、框架。
- 不擅自修改项目架构和分层结构。
- 大重构先给方案，再执行。
- 严格遵循 TDD：test first by default。
- 聚焦 Java 工程，回复简洁。
- 写 SQL、事务、锁、并发代码时要额外自检。
- 代码、文档或注释需要作者标识时，作者统一写 `Jeff.Liu`，禁止写 `Codex`；修改已包含 `作者：Codex` 或 `@author Codex` 的文件时，同步替换为 `Jeff.Liu`。

## Graph Tool Routing

有图谱就先用图谱，少用 grep/cat/read。

| 任务 | 优先工具 |
|---|---|
| review / diff 风险 / 测试缺口 | code-review-graph：`detect_changes(detail_level="minimal")` |
| 导航：X 在哪、谁调用 X、X 到 Y 链路、改 X 影响谁 | CodeGraph：`codegraph_explore` / `codegraph_node` |
| 架构 / 模块依赖 / 全局问题 | graphify 报告或 code-review-graph architecture tools |
| 逐字核实和编辑 | 图定位后再读具体文件 |

硬规则：导航和影响面先问图；code-review-graph 默认 `minimal`；已有 agent/图结果不要重复 grep。

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tools** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them. `codegraph_node` returns one symbol's source + callers, or reads a whole file with line numbers. If the tools are listed but deferred, load them by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` and `codegraph node <symbol-or-file>` print the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

<!-- AGENTMEMORY_START -->
## AgentMemory

Use AgentMemory for durable cross-session memory when the user mentions memory, agentmemory, claude-mem, semantic recall, or asks to remember/recall prior context. Prefer the AgentMemory MCP tools after a Codex restart/new task. If tools are not visible, verify with `agentmemory status` and explain that MCP servers load on the next launch. Do not persist secrets or sensitive data unless explicitly requested and appropriate.
<!-- AGENTMEMORY_END -->

<!-- PONYTAIL_START -->
## Ponytail

Use Ponytail on coding tasks to avoid over-engineering: understand the touched code first, then choose the smallest correct implementation. Prefer existing project patterns, standard library, native platform features, and installed dependencies before adding code or dependencies. Do not remove validation, security, accessibility, or explicit user requirements. Commands/skills: `ponytail`, `ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`. Default mode is full; `stop ponytail` / `normal mode` turns it off.
<!-- PONYTAIL_END -->

开始工作前，读取并遵循 `~/.codex/RTK.md` 中的规则。
