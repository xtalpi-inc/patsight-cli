# PatSight CLI 新功能重点测试报告（dev 分支 · 6/10 更新）

## 1. 结论总览

| 编号 | 功能点 | 结论 | 核心依据 |
| --- | --- | --- | --- |
| R1 | 默认提交全部页码 | ✓ 通过 | 全页任务完成，`pdf_pages` 与 PDF 总页数一致 |
| R2 | 指定页码范围提交 | ✓ 通过 | 三类任务 `--pages 1-2` 均 `done`，`pdf_pages=2` |
| R3 | 结构与活性按类型/格式导出 | ✓ 通过 | 全页 9 种组合在 WO2010111432A1 均成功；ADMET 已补齐验证 |
| R4 | 合成路线按格式导出 | ✓ 通过 | `reactions` + `xlsx/json` 导出成功 |
| R5 | IUPAC Name 按格式导出 | ✓ 通过 | 全页 `structures` csv/xlsx/sdf 均成功 |
| R6 | 默认结果导出 | ✓ 通过 | 默认 `bioactivity/csv`，有活性数据时导出成功 |

![重点需求测试结论](evidence/r3_supplement_20260610/screenshots/05_focused_requirements_summary.png)

## 2. 测试目标

在 `origin/dev` 分支（`8b67144`）上验证页码范围提交与结果导出能力（R1–R6）。

- 主样例：`WO2010111432A1.pdf`（R1/R2/R3/R6）
- R3 补充样例：`WO2012016698A2.pdf`、`WO2012107708A1.pdf`（ADMET 专项）
- R4/R5 历史验证：`WO2004087707A1-part-example.pdf`（远程任务 job_id 仍有效）

测试环境：Windows 10、Python 3.11.3、patsight-cli 0.1.0。以下命令均在仓库根目录执行。

## 3. R1 默认提交全部页码

**结论：✓ 通过**

| 依据 | 说明 |
| --- | --- |
| 样例 | WO2010111432A1.pdf（79 页） |
| 任务 | `2064622971598807040`，status=done |
| 结果 | `pdf_pages=79`，未传 `--pages` 时处理全部页 |

### 3.1 复现命令

```powershell
# 提交（默认全页）
python -m patsight_cli.cli.main submit --pdf-path WO2010111432A1.pdf --job-type structureAndActivity

# 查询状态（替换为 submit 返回的 job_id，已验证示例）
python -m patsight_cli.cli.main status --job-id 2064622971598807040 --job-type structureAndActivity
```

**预期：** status=done，raw.task_info.pdf_pages=79。

## 4. R2 指定页码范围提交

**结论：✓ 通过**

| 任务类型 | job_id（已验证） | 结果 |
| --- | --- | --- |
| structureAndActivity | 2064629905349550080 | done，pdf_pages=2 |
| reaction | 2064587072555065344 | done，pdf_pages=2 |
| iupac | 2064587106386321408 | done，pdf_pages=2 |

三类任务 `--pages 1-2` 均生效。

### 4.1 复现命令

```powershell
# 结构与活性（1-2 页）
python -m patsight_cli.cli.main submit --pdf-path WO2010111432A1.pdf --job-type structureAndActivity --pages 1-2
python -m patsight_cli.cli.main status --job-id 2064629905349550080 --job-type structureAndActivity

# 合成路线（1-2 页）
python -m patsight_cli.cli.main submit --pdf-path WO2010111432A1.pdf --job-type reaction --pages 1-2

# IUPAC Name（1-2 页）
python -m patsight_cli.cli.main submit --pdf-path WO2010111432A1.pdf --job-type iupac --pages 1-2

# reaction / iupac 状态验证（历史已验证 job_id）
python -m patsight_cli.cli.main status --job-id 2064587072555065344 --job-type reaction
python -m patsight_cli.cli.main status --job-id 2064587106386321408 --job-type iupac
```

**预期：** 三类任务 status=done，pdf_pages=2。

## 5. R3 结构与活性导出选择

**结论：✓ 通过**（CLI 能力已完整验证；此前「部分通过」为样例数据不足，非功能缺陷）

| 导出类型 | csv | xlsx | sdf |
| --- | --- | --- | --- |
| bioactivity（活性数据） | ✓ | ✓ | ✓ |
| admet（ADMET 数据） | ✓ | ✓ | ✓ |
| namedStructures（具名化学结构） | ✓ | ✓ | ✓ |

- 任务 job_id：`2064622971598807040`（WO2010111432A1 全页）
- 统计：`structures_total=34`，`properties=7`

### 5.1 复现命令（全页 SAR 任务，9 种组合）

```powershell
$JOB = "2064622971598807040"
$OUT = "evidence/r3_supplement_20260610/output"

# 活性数据
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type bioactivity --format csv --workdir $OUT
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type bioactivity --format xlsx --workdir $OUT
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type bioactivity --format sdf --workdir $OUT

# ADMET 数据
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type admet --format csv --workdir $OUT
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type admet --format xlsx --workdir $OUT
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type admet --format sdf --workdir $OUT

# 具名化学结构
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type namedStructures --format csv --workdir $OUT
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type namedStructures --format xlsx --workdir $OUT
python -m patsight_cli.cli.main result --job-id $JOB --job-type structureAndActivity --export-type namedStructures --format sdf --workdir $OUT
```

**预期：** 9 条命令均 exit=0；bioactivity CSV 含 IC50/EC50 列，admet CSV 含 PK 药代列。

### 5.2 ADMET 专项补充（可选）

```powershell
# WO2012016698A2 — 仅 admet / namedStructures 有数据
python -m patsight_cli.cli.main result --job-id 2064623050174898176 --job-type structureAndActivity --export-type admet --format csv --workdir evidence/r3_supplement_20260610/output

# WO2012107708A1
python -m patsight_cli.cli.main result --job-id 2064623110337994752 --job-type structureAndActivity --export-type admet --format csv --workdir evidence/r3_supplement_20260610/output
```

## 6. R4 合成路线导出选择

**结论：✓ 通过**

| 格式 | 结果 |
| --- | --- |
| reactions / xlsx | ✓ 成功 |
| reactions / json | ✓ 成功 |

依据：reaction 任务 `2064587072555065344`（`--pages 1-2` 提交）。

### 6.1 复现命令

```powershell
# 提交（若需新建任务）
python -m patsight_cli.cli.main submit --pdf-path WO2010111432A1.pdf --job-type reaction --pages 1-2

# 导出（已验证 job_id）
python -m patsight_cli.cli.main result --job-id 2064587072555065344 --job-type reaction --export-type reactions --format xlsx
python -m patsight_cli.cli.main result --job-id 2064587072555065344 --job-type reaction --export-type reactions --format json
```

**预期：** 生成 Reaction.xlsx 与 Reaction.json。

## 7. R5 IUPAC Name 导出选择

**结论：✓ 通过**

| 格式 | 结果 |
| --- | --- |
| structures / csv | ✓ 成功（structures_total=16） |
| structures / xlsx | ✓ 成功 |
| structures / sdf | ✓ 成功 |

依据：全页 IUPAC 任务 `2064595317533319168`。

### 7.1 复现命令

```powershell
# 提交（若需新建全页 IUPAC 任务）
python -m patsight_cli.cli.main submit --pdf-path WO2010111432A1.pdf --job-type iupac

# 导出（已验证 job_id）
python -m patsight_cli.cli.main result --job-id 2064595317533319168 --job-type iupac --export-type structures --format csv
python -m patsight_cli.cli.main result --job-id 2064595317533319168 --job-type iupac --export-type structures --format xlsx
python -m patsight_cli.cli.main result --job-id 2064595317533319168 --job-type iupac --export-type structures --format sdf
```

**预期：** 三种格式均 exit=0，CSV 含 IUPAC 结构列。

## 8. R6 默认结果导出

**结论：✓ 通过**

| 依据 | 说明 |
| --- | --- |
| 默认规则 | structureAndActivity → bioactivity / csv |
| 验证任务 | WO2010111432A1 全页 `2064622971598807040` |
| 结果 | 导出成功，列含 IC50/EC50 活性数据 |

### 8.1 复现命令

```powershell
python -m patsight_cli.cli.main result --job-id 2064622971598807040 --job-type structureAndActivity
```

**预期：** export_type=bioactivity，file_format=csv，exit=0。

## 9. 失败项根因（均非 CLI 缺陷）

| 现象 | 根因 | 是否开发问题 |
| --- | --- | --- |
| 窄页码 bioactivity / admet 导出失败 | 页内无对应数据表 | 否 |
| WO2012016698 / WO2012107708 bioactivity 失败 | 专利无活性表 | 否 |
| 早期 WO2004087707 admet 失败 | 样例无 ADMET 数据 | 否 |

## 10. 基准回归

```powershell
python -m pytest -q
```

结果：**52 passed**

## 11. 最终结论

**dev @ 8b67144 六项需求均可验收通过。** R3 使用 WO2010111432A1 等补充样例后，活性 / ADMET / 具名结构三类导出及 csv / xlsx / sdf 三种格式均已验证通过。
