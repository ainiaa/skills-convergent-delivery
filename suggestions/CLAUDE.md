# Global Claude Code Memory — Java Fullstack + Karpathy Engineering
# Global effective, all projects, all conversations must comply
# origin CLAUDE.md https://github.com/forrestchang/andrej-karpathy-skills

## 0. NON-NEGOTIABLE TDD RULE (TEST FIRST ABOVE ALL)
- ALL CHANGES (feature, bugfix, refactor) MUST BE TEST FIRST
- Write test case BEFORE writing business code
- Tests must include normal, boundary, exception scenarios
- Refactor ONLY when all existing tests pass
- No test, no code; no untested commit

## 1. Core Engineering Mindset (Andrej Karpathy Standard)
1. Think step-by-step before writing code; prioritize correctness, readability, maintainability over clever tricks.
2. Prefer simple, explicit, boring code over over-engineered, abstract, premature optimization.
3. All changes must be verifiable, testable, traceable.
4. Fix root cause, not symptoms; avoid workaround hacks.
5. Incremental development: small commits, small changes, verify step by step.
6. Clear error handling, clear boundary definition, clear responsibility splitting.
7. Reuse proven patterns; do not invent new architecture or custom conventions without approval.
8. When debugging: reproduce first, locate root cause, then fix, finally add test to prevent regression.

## 2. Tech Stack & Architecture
- Java: 8 / 11 / 21
- Framework: Spring Boot, Spring MVC, Spring Transaction
- ORM: MyBatis / MyBatis-Plus
- Database: MySQL 8.0+
- Cache: Redis + Redisson
- Architecture: Controller → Service → Mapper layered structure
- API: RESTful style
- Build: Maven / Gradle
- **Gradle 禁 `--refresh-dependencies`**：RELEASE 版本升级时 Gradle 会自动拉取新 JAR，加此参数强制全量重下载所有依赖（耗时 4-6 分钟），仅 SNAPSHOT 且 `changing = true` 仍不生效时例外。
- Test: JUnit 5, Mockito, Integration Test

## 3. Java Coding Specification
- Class: UpperCamelCase
- Method/Variable: camelCase
- Constant: UPPER_SNAKE_CASE
- Database table/column: snake_case
- No Pinyin, no meaningless abbreviation, no magic number.
- Controller: only parameter receive, validation, response wrap, routing.
- Service: business logic, transaction control, aggregation, third-party invoke.
- Mapper: pure DB operation, no business logic.
- Entity mapping DB field; DTO/VO isolate input/output.
- Uniform global exception handling, no scattered try-catch.

## 4. Transaction & Security
- Write operation (insert/update/delete) must use @Transactional.
- Parameter validation with @Valid.
- Prevent SQL injection, XSS, unauthorized access.
- No hardcode key、password、secret、environment config.
- External API must config timeout、retry、circuit breaker、exception catch.

## 5. MySQL & SQL Rules
- Forbid SELECT *
- Forbid full table DELETE / UPDATE without WHERE
- Avoid index invalid writing: function wrap column, implicit conversion
- Pagination must use limit / page helper
- Use prefix fuzzy match only, avoid leading % fuzzy query
- High frequency query fields need index evaluation
- Unified time field: timestamp / datetime, unified time zone

## 6. Cache & Distributed
- Redis key unified business prefix, isolated by module
- Prevent cache penetration / breakdown / avalanche
- Distributed lock use Redisson
- Cache strategy: update DB first, then delete cache

## 7. Log Specification
- Use SLF4J unified log
- Key entry、exit、exception、third-party call must be logged
- Sensitive data desensitization, no full sensitive print

## 8. Unit Test Mandatory Rule (Hard Constraint)
- All business core code, service layer, tool class, common component must be covered by unit test.
- Overall business code unit test coverage ≥ 85%
- Use JUnit5 + Mockito for mock dependency
- Test scope: normal scenario, boundary value, exception scenario, abnormal parameter
- After new feature / bug fix / refactor: must write/update test cases
- Refactoring must keep test passing, ensure no regression
- Do not write perfunctory empty test; test must assert result

## 9. Code Quality & Refactor
- Return empty collection instead of null (Collections.emptyList())
- Single responsibility for method, forbid giant long method
- Forbid DB / Redis / remote call in loop
- Complex logic add clear comment with business background
- Refactor keep original business behavior unchanged

## 10. AI Behavior Constraints
- Output production-ready, directly online available code.
- Do not introduce new middleware / dependency / framework without confirmation.
- Do not modify project architecture and layered structure arbitrarily.
- Provide optimization plan first before large refactoring.
- Follow TDD strictly: test first always.
- Focus on Java engineering, concise reply, no redundant nonsense.
- When writing SQL / transaction / lock / concurrent code, self-check carefully.
# graphify
- **graphify** (`~/.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else.

# code-review-graph
Initialize code-review-graph synchronously upon project initialization.Run the following commands:
code-review-graph install --platform claude && code-review-graph build

# 代码图谱路由（codegraph / code-review-graph / graphify）— 装了图先用图，省 token

> 三者名字像、定位不重叠，**按任务选**；图先于 grep/cat/Read。**仅当当前项目已 build 对应图谱时**适用（图谱按项目建，未建则退回普通检索）。**跨仓库对比图谱覆盖不到，用子 agent。**

| 任务 | 用谁 | 怎么用 |
|---|---|---|
| review / 对比分支 / "diff 改了啥、风险、测试缺口" | **code-review-graph** | 先 `get_minimal_context(task=...)`，再 `detect_changes(base=..., detail_level="minimal")`。**严禁 `standard`**（会吐十几万字符撑爆上下文） |
| 导航："X 在哪 / 谁调用 X / X→Y 链路 / 改 X 影响谁" | **codegraph** | 优先 `codegraph_context`（一次=search+node+callers+callees）；survey 用 `codegraph_explore`（单次封顶），别开一堆 Read |
| 架构 / 模块依赖 / God Nodes / 全局问题 | **graphify** | `cat graphify-out/GRAPH_REPORT.md` 一次拿全；`/graphify query`、`/graphify path`。不重复 build（贵） |
| 改某文件某行 / 逐字核实 | Read(offset/limit) | 图给结构、不给可编辑源码；只 Read 要动的 2-3 个文件 |

**硬规则**：① 导航/影响面先问图、确认到行再 Read；② code-review-graph 一律 `minimal` + 先 `get_minimal_context`；③ codegraph 合并调用（`_context`/`_explore`），别拆多次 `_node`+Read；④ 已派 agent 搜的不再自己 grep。

@~/.claude/RTK.md
