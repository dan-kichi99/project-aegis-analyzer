# SPEC-056: Solved Status Consistency

## 目的

Flag発見時のJudgeResultとCLI表示の矛盾を解消する。

## Solved判定

次の条件をSolvedとする。

```python
result.flag is not None