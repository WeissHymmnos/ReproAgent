# ReproAgent 最终产品汇报

面向业务与投研管理层的产品阶段汇报（非技术设计文档）。

| 文件 | 说明 |
|------|------|
| `reproagent_product_report.tex` | LaTeX 源稿（`ctexart` + XeLaTeX） |
| `reproagent_product_report.pdf` | 编译产物 |

## 重新编译

```bash
cd docs/product-report
xelatex -interaction=nonstopmode reproagent_product_report.tex
xelatex -interaction=nonstopmode reproagent_product_report.tex
```

或：

```bash
latexmk -xelatex -interaction=nonstopmode reproagent_product_report.tex
```
