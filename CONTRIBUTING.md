# Contributing to minimal-agent

欢迎贡献！这个项目遵循以下流程：

## 贡献方式
1. Fork 仓库。
2. 在自己分支上进行修改，分支命名建议使用 `feature/...` 或 `fix/...`。
3. 提交并推送修改。
4. 创建 Pull Request 到 `master` 分支。

## 提交规范
- 提交信息格式建议：`type(scope): subject`
- type 推荐：`feat`, `fix`, `docs`, `chore`, `test`, `refactor`
- subject 简明扼要，使用英文小写。

## 代码规范
- Python 代码遵循 PEP 8。
- 添加新功能时请补充测试。
- 运行方式：
  ```bash
  python -m pytest -q
  ```

## 报 bug
请提供：
- 复现步骤
- 期望结果
- 实际结果
- 相关日志或错误堆栈

## 提需求
请描述：
- 你想要什么功能
- 这个功能会解决什么问题
- 可能的使用场景
