# cc-switch-adapter

Agent 侧 **closed-pipe**：默认 **park** 入库；**canonical-id** + **per-app enable**；**live**（`enabled_*`）才是「现在开了什么」；**project-slot** 只是可脏的启用集快照（slot⊃live ≠ 漏开）。

**runtime-first**：本机 DB/settings/磁盘；云端手册可选；不依赖本机源码树。

对 agent：`安装先 park` · `迁移 bare id` · `doctor 只读` · `fat snapshot → resnap` · `slot 差集不当 enable`

```bash
python3 doctor.py                  # 真机
python3 doctor.py --root fixtures/clean
python3 -m unittest tests.test_doctor_report -v
```

见 [SKILL.md](SKILL.md)。参考：`doctor.py` · `doctor.md` · `db-schema.md` · `lock-file.md` · `file-layout.md`。

MIT。cc-switch 版权归其作者。
