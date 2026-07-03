# patent export 空 zip 根因与解决方案

## 背景

用户执行以下命令后，命令成功退出，但生成的 zip 中没有实际导出内容：

```powershell
patsight-cli patent export --zip --fetch-all --no-editors -o export-all.zip
```

终端返回：

```json
{
  "ok": true,
  "zip_path": "C:\\Users\\qingnan.xie\\.local\\share\\patsight-cli\\output\\export-all.zip",
  "task_count": 0,
  "exported_count": 0,
  "skipped_count": 0,
  "warnings": []
}
```

zip 实际包含 `manifest.json` 和 `metadata.json`，其中 `manifest.tasks` 为空。问题不是 zip 写入失败，而是导出前没有收集到任何专利任务。

## 复现证据

本次在当前账号下执行了只读验证命令：

```powershell
patsight-cli patent list --per-page 1
patsight-cli patent list --per-page 1 --view 0
patsight-cli patent list --per-page 1 --view 1
```

三条命令均返回：

```json
{
  "code": 1,
  "data": {
    "count": 0,
    "task_info": []
  },
  "error": "",
  "message": ""
}
```

但共享文件夹接口可以看到数据：

```powershell
patsight-cli shared-folder list --view 0
```

返回 folder `3188` 和 `3192`。

继续验证：

```powershell
patsight-cli shared-folder patents list --folder-id 3188
patsight-cli shared-folder patents list --folder-id 3192
```

结果分别能看到 `3188` 下 6 条任务、`3192` 下 1 条任务，且任务状态为 `Done`。

但是：

```powershell
patsight-cli patent list --folder-id 3188 --per-page 1
patsight-cli patent list --folder-id 3192 --per-page 1
```

仍返回 `count: 0`。

## 代码链路

`patent export --zip` 的入口位于 `src/patsight_cli/cli/main.py`：

```python
result = export_patents_to_zip(
    client,
    output_path=args.output,
    export_type=args.export_type,
    file_format=args.format,
    fetch_all=args.fetch_all,
    include_editors=not args.no_editors,
    list_kwargs=_patent_list_kwargs(args),
    filter_kwargs={
        "remark": args.remark,
        "creator_email": args.creator_email,
        "unfiled": args.unfiled,
        "multi_folder": args.multi_folder,
    },
)
```

`export_patents_to_zip()` 位于 `src/patsight_cli/export/batch_zip.py`，第一步调用：

```python
rows = collect_patents(client, fetch_all=fetch_all, **list_kwargs, **filter_kwargs)
```

`collect_patents()` 当前只通过 `client.list_accessible_patents()` 收集任务。该方法最终请求：

```python
GET /patent/api/v2/extractor/tasks
```

当这个接口返回 `task_info: []` 时，`rows` 为空，后续不会进入单任务导出循环，只会写入空的 `manifest.json` 和 `metadata.json`。

共享文件夹专利列表走的是另一条接口：

```python
POST /patent/api/v2/extractor/task/folder/task/get
```

对应方法是 `PatSightClient.list_shared_folder_patents(folder_id)`。本次验证中，该接口可以返回 folder 内的任务，而 `/v2/extractor/tasks?folder_id=...` 返回空。

## 根因

根因是 CLI 批量 zip 导出依赖的任务列表接口与共享文件夹专利接口数据不一致：

- `patent export --zip` 只依赖 `patent list` 同源的 `/v2/extractor/tasks`。
- 当前账号下 `/v2/extractor/tasks` 默认返回空。
- 即使指定 `--folder-id 3188` 或 `--folder-id 3192`，`/v2/extractor/tasks` 仍返回空。
- 但 `shared-folder patents list --folder-id ...` 使用的共享文件夹接口可以返回实际任务。

因此，命令成功生成 zip，但 `task_count=0`。这属于数据来源选择问题，不是压缩包生成失败，也不是 `--no-editors` 或 `--fetch-all` 导致内容被过滤。

## 立即可用的绕行方案

如果只是需要导出某个共享文件夹内已有任务，可以先通过共享文件夹接口获取任务 id：

```powershell
patsight-cli shared-folder patents list --folder-id 3188
```

然后对单个任务导出：

```powershell
patsight-cli export --job-id <task_id>
```

这个方案可以绕过当前 `patent export --zip` 的批量任务收集问题，但缺点是需要手动或脚本循环多个 `task_id`，无法直接得到统一 zip manifest。

## 推荐修复方案

在 `patent export --zip` 的任务收集逻辑中，对共享文件夹场景增加稳定数据源：

当用户传入 `--folder-id <id>` 且 `<id> > 0` 时，优先使用或兜底使用 `client.list_shared_folder_patents(folder_id)` 收集任务，然后复用现有单任务导出与 zip 打包逻辑。

推荐策略：

1. 保留现有 `list_accessible_patents()` 逻辑，避免影响个人任务列表、无 folder 导出和后端筛选能力。
2. 当指定 `folder_id > 0` 时，先调用 `list_accessible_patents(folder_id=...)`。
3. 如果该接口返回非空，继续使用现有结果。
4. 如果该接口返回空，再调用 `list_shared_folder_patents(folder_id)` 作为兜底。
5. 对共享文件夹兜底结果进行同样的本地过滤和状态判断。
6. 如果兜底接口也为空，则生成空 zip，但在 `warnings` 中说明没有可导出的任务来源。

这种方式最小化影响面，同时修复当前已验证的数据不一致问题。

## 实施计划

### 任务 1：新增共享文件夹任务收集分支

修改 `src/patsight_cli/export/batch_zip.py`：

- 在 `collect_patents()` 中识别 `folder_id`。
- 当 `folder_id` 为正整数时允许调用 `client.list_shared_folder_patents(folder_id)`。
- 复用 `patent_rows_from_response()` 解析共享文件夹接口返回的 `data.data`。

验收标准：

- `folder_id` 为空时行为不变。
- `folder_id=0` 时行为不变。
- `folder_id>0` 且 `/v2/extractor/tasks` 返回空时，可以从共享文件夹接口拿到任务。

### 任务 2：补齐兜底路径过滤规则

共享文件夹接口返回的是完整列表，不能无视用户筛选参数。至少需要保留以下规则：

- `status`：本地按 `row["status"]` 大小写不敏感匹配。
- `is_collection`：本地按布尔值匹配。
- `name` / `name_field`：优先按指定字段匹配，未指定字段时可匹配 `file_name`、`title`、`id`。
- `exclude_action`：本地排除 `action` 或 `action_type` 匹配的任务。
- `remark`、`creator_email`、`unfiled`、`multi_folder`：继续复用现有 `filter_patent_rows()`。

对无法可靠本地复刻的筛选条件，例如 `searched_smiles`，应保守处理：

- 如果主列表接口为空且启用了 `searched_smiles`，不要静默导出共享文件夹全部任务。
- 返回明确 warning 或错误，提示该筛选依赖后端列表接口。

验收标准：

- 启用 `--status done --folder-id 3188` 时只导出完成任务。
- 启用无法兜底的后端专属筛选时，不会误导出过多任务。

### 任务 3：增加测试覆盖

修改或新增 `tests/test_patent_export_zip.py`：

- 覆盖 `list_accessible_patents()` 返回空但 `list_shared_folder_patents()` 返回任务的场景。
- 覆盖 `folder_id` 未指定时不调用共享文件夹接口。
- 覆盖 `folder_id=0` 时不调用共享文件夹接口。
- 覆盖共享文件夹兜底结果仍会跳过非完成状态任务。
- 覆盖 `searched_smiles` 等无法兜底筛选不会误导出全部任务。

验收标准：

```powershell
pytest tests/test_patent_export_zip.py
```

通过。

### 任务 4：端到端验证

在当前账号下验证：

```powershell
patsight-cli patent export --zip --folder-id 3188 --fetch-all --no-editors -o folder-3188.zip
```

预期：

- 返回 `task_count` 大于 0。
- 返回 `exported_count` 大于 0，前提是 folder 内存在 `Done` 任务且单任务导出接口可用。
- zip 中包含 `manifest.json`、`metadata.json` 和 `exports/*`。

同时验证原命令：

```powershell
patsight-cli patent export --zip --fetch-all --no-editors -o export-all.zip
```

如果默认任务列表仍为空，应继续返回 `task_count=0`，但这是符合当前后端列表数据的结果。

## 风险与边界

主要风险是共享文件夹接口和任务列表接口的筛选语义不完全一致。修复时不能为了让 zip 有内容而静默导出用户没有筛选到的任务。

需要特别注意：

- `searched_smiles` 这类后端专属筛选不能随意本地模拟。
- 大共享文件夹如果接口不分页，可能一次返回很多任务，需要确认接口规模上限。
- 共享文件夹接口返回的字段可能少于 `/v2/extractor/tasks`，manifest 中缺失字段应保持为 `null` 或缺省，而不是伪造。
- 现有个人列表导出不能被共享文件夹兜底逻辑影响。

## 最终建议

短期建议用户使用：

```powershell
patsight-cli patent export --zip --folder-id 3188 --fetch-all --no-editors -o folder-3188.zip
```

并在代码层修复 `--folder-id` 场景的数据源选择。

长期建议和后端确认 `/v2/extractor/tasks?folder_id=...` 与 `/v2/extractor/task/folder/task/get` 的语义差异。如果后端确认前者不会稳定返回共享文件夹内任务，则 CLI 应把共享文件夹导出明确建模为独立数据源，而不是继续依赖通用任务列表接口。
