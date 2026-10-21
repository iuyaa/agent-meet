# 从 Agent Chat 迁移到 Meet

简体中文 · [English](MIGRATION.en.md)

产品名为 **Meet**，仓库和 skill 为 **agent-meet**，调用名为 `$agent-meet`。
v0.8.1 是独立项目与命名迁移，保持 v0.8 的讨论行为。

## 安装和继续原讨论

1. 将新安装包中的 `agent-meet` 放入宿主的 skill 目录。仓库根目录就是技能根目录。
2. 移除旧的 `agent-chat` 技能目录，避免重复发现。先确认讨论数据保存在技能目录之外；
   若曾放在目录内，完整备份数据库及所有同名前缀目录后再移除，不能只备份 SQLite。
3. 保留当前长会话，让它读取新版 `agent-meet/SKILL.md`。后续调用改为 `$agent-meet`。
4. 已运行的页面服务先执行旧版或新版 `view.py close --room ORIGINAL_ROOM`，
   再用新版 `view.py start --room ORIGINAL_ROOM --open`。只刷新浏览器不会更新服务代码。
5. 继续讨论时，使用原房间路径执行 status / extend / reply 或 group round。
   不运行 init，不新建房间或角色会话。原有预算与追加审批规则保持不变。

`ROOM.sqlite` 与 `.consult/`、`.group/`、`.peers/`、`.view/` 等同名前缀目录必须保留。
pi 的原生会话文件也在 `.peers/` 中；Claude/Codex/OpenCode 原生记录仍依赖其 CLI 存储。
若更换机器或项目路径，还需保证已保存的工作目录、CLI 路径和原生会话可用；
本次改名不会自动搬运这些路径或账号资料。

## 保持兼容的内部名称

SQLite 版本与所有状态文件名均未更改。网页继续使用原来的
`agent-chat-token` / `agent-chat-folds` 存储键，以保留已打开页面的访问令牌和折叠设置。
OpenCode 内部的 `agent-chat` 讨论 agent 名称也保留，以恢复已有 session；
这是 CLI 适配标识，不是需要继续安装的旧 skill。
已有报表和历史消息不会被批量改写；新导出文件名为 `agent-meet-report.md`。
历史 `releases/agent-chat-*.zip` 保持原样，不冒充新的 Meet 安装包。

## 历史和许可

本仓库提取自 [iuyaa/golutra 的独立技能目录](https://github.com/iuyaa/golutra/tree/cc3a384a1b35752a58c20b018f4bb7ba7d4568a5/skills/agent-chat)，
保留该目录九次提交的作者、时间、消息和文件树；移到仓库根目录后提交 SHA 会变化。
其它 Golutra 应用代码没有进入独立项目。

本技能为独立实现，未复制 Golutra 应用源码或资产。保留原 MIT 版权声明；
Marked、DOMPurify 的上游许可与版本说明位于 `web/vendor/`。

## v0.10 审核收尾

新版读取已有前台房间时，已获接受但没有最终归档记录的草案会显示“待整理最终结论”。
这是补全最后审核意见的步骤，不会重建房间、删除草案或自动调用模型。
让原主持人读取完整审核并按 `references/finalization.md` 保存最终稿即可。
原始手动/后台通信协议未安装 lifecycle 元数据时维持原有确认行为。
