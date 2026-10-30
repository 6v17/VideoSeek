# 贡献指南

谢谢你愿意改 VideoSeek。

- 缺陷和小修复可以直接开 [issue](https://github.com/6v17/VideoSeek/issues) 或 pull request。
- 新功能，以及会改索引、数据库或文件格式的改动，先开 issue。写清要解决什么、动哪些数据。确认后再写代码。
- 一个 pull request 只做一件事。说明为什么改，以及你怎么验证的。
- 新代码遵守 [`docs/engineering.md`](docs/engineering.md)。按阶段把边界划清：一个模块一件事。文件变长时先找能切开的边界，不要为了行数拆碎，也不要把无关的事继续揉进同一个文件。
- 加东西时先复用已有入口。索引放在 `src/storage`，模型推理放在 `src/core`，业务逻辑放在 `src/services`，网络请求先找已有调用。不要为单个功能再写一套。
- 改用户可见的文案时，同时改 `src/app/i18n.py` 里的中文和英文。这句如果已经在 `src/app/copy_overrides.py` 里，两处一起改。

## 平台与依赖

当前会持续维护和打包的平台是 Windows 10/11。其他平台上的修复也欢迎，请在说明里写上系统版本和你实际跑过的测试。

某个包装不上时，在 issue 里写明 Python 版本、系统和完整报错，先不要改仓库里的版本约束。

## 本地检查

环境准备见 [`docs/quickstart.md`](docs/quickstart.md)。项目要求 Python 3.10 或更高，持续集成跑的是 3.10。若某个更新的版本没有 `onnxruntime` 或 `faiss-cpu` 的预编译包，请在说明里写明。

```bash
python -m ruff check src ui tests scripts main.py
python -m pytest tests/ -q
```

某条测试只在你的平台上失败，并且依赖另一种系统的路径或权限时，给这一条加上平台标记。写法见 `tests/test_faiss_index_io.py`：

```python
@unittest.skipUnless(sys.platform == "win32", "Windows FAISS ASCII staging root")
```

不要把整个测试文件跳过。

## 许可

本项目以 [AGPL-3.0](LICENSE) 发布。派生仓库请保留对上游 <https://github.com/6v17/VideoSeek> 的指向，并遵守 AGPL 对修改说明的要求。
