# tiny-agent

一个**用来当夹具**的极小 Python 仓库：只演示「agent 把消息交给传输层」这一条链路。
它不是产品代码，存在的理由是给 RepoLearn 的抓取 / 分析 / 升级三处提供一份可读、
可逐字节比对的真代码。

## 跑一下

```bash
python -m tiny.main
```

## 为什么只有四个文件

夹具的价值在于「二次运行逐字节一致」：文件越少，「1 modified + 1 added + 1 removed」
这条断言（M10 / T-UPG-2）就越不可能被无关改动污染。传输层具体是谁（总线还是路由器）
由 `tiny/agent.py::default_bus()` 决定，调用方不需要知道。
