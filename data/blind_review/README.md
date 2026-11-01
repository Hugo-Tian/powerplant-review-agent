# 专工盲评

- `专工盲评表.xlsx`：发给专工填写的表。只含虚构工单原文，不含系统结果。
- `key.json`：答案键，**不要发给专工**。

重新生成（例如评测结果更新后）：

```
.jiuwen-venv\Scripts\python.exe scripts/make_blind_review.py
```

收回后计分（可以一次传入多份）：

```
.jiuwen-venv\Scripts\python.exe scripts/score_blind_review.py 收回\专工A.xlsx 收回\专工B.xlsx --out data/eval/blind_review.json --cases-out data/synthetic/expert_cases.json
```

建议至少 2 位专工，互不商量，以便估计专工之间的一致程度。收回的原始表格如含个人信息，不要提交到仓库。
