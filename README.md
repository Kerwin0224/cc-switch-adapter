# cc-switch-adapter

Agent 侧 **closed-pipe**：**park**（未点名 app 的 adapter-policy）或 **install-enable**（点名 app，≈ 官方）；**live** 才是「现在开了什么」；**fat snapshot** → resnap/scrub JSON，live 只经 dispatch/确认 apply。

**runtime-first**：本机 DB/settings/磁盘；云端可选。

对 agent：`未点名 → park` · `点名 app → install-enable` · `doctor 只读` · `fat → slot 卫生`

```bash
python3 doctor.py                  # 真机
python3 doctor.py --root fixtures/clean
python3 -m unittest tests.test_doctor_report -v
```

见 [SKILL.md](SKILL.md)。参考：`doctor.py` · `doctor.md` · `db-schema.md` · `lock-file.md` · `file-layout.md`。

MIT。cc-switch 版权归其作者。
