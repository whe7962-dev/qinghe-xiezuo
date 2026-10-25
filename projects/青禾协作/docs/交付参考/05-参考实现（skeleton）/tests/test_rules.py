"""业务规则测试：写回门槛、字段级更新、重复导入去重。"""
from app.models import Task, Chat, Suggestion, NO_TASK_MARK
from app.rules import can_apply, apply_suggestion, dedup_new_chats, unchanged_tasks


def make_tasks():
    return [
        Task("W-01", "账单导出支持全部结果", "林川", "开发中", "9 月 18 日", "跨页导出无遗漏，总额可核对"),
        Task("W-02", "邀请新成员前增加审批", "周宁", "本期不做，保留待讨论", "未定", "未定"),
    ]


def test_can_apply_only_confirmed():
    assert can_apply(Suggestion("W-01", "责任人", "林川", "周宁", decision="采纳"))
    assert can_apply(Suggestion("W-01", "责任人", "林川", "周宁", decision="修改后采纳", modified_value="周宁"))
    assert not can_apply(Suggestion("W-01", "责任人", "林川", "周宁", decision="待确认"))
    assert not can_apply(Suggestion("W-01", "责任人", "林川", "周宁", decision="否决"))


def test_apply_changes_only_target_field():
    tasks = make_tasks()
    s = Suggestion("W-01", "责任人", "林川", "周宁", decision="采纳",
                   evidence=[{"chat_id": "B-01", "quote": "W-01 改由周宁接手"}])
    assert apply_suggestion(tasks, s) is True
    assert tasks[0].owner == "周宁"
    # 其余字段保持不动
    assert tasks[0].due == "9 月 18 日"
    assert tasks[0].item == "账单导出支持全部结果"
    assert tasks[0].acceptance == "跨页导出无遗漏，总额可核对"


def test_apply_ignores_unconfirmed():
    tasks = make_tasks()
    s = Suggestion("W-01", "责任人", "林川", "周宁", decision="待确认")
    assert apply_suggestion(tasks, s) is False
    assert tasks[0].owner == "林川"


def test_no_new_task_for_unknown():
    tasks = make_tasks()
    s = Suggestion(NO_TASK_MARK, "", "", "待核实", decision="采纳")
    assert apply_suggestion(tasks, s) is False
    assert len(tasks) == 2


def test_dedup_same_batch():
    chats = [
        Chat("A-01", "9 月 15 日 09:00", "客户甲／客服转交", "账单比页面少了两千多"),
        Chat("A-01", "9 月 15 日 09:00", "客户甲／客服转交", "账单比页面少了两千多"),
        Chat("A-02", "9 月 15 日 10:00", "客服核查", "只导出了第一页"),
    ]
    new_chats, new_keys = dedup_new_chats(chats, set())
    assert len(new_chats) == 2  # A-01 重复正文去重
    # 已处理过的 key 再次导入 → 全部跳过
    again, again_keys = dedup_new_chats(chats, new_keys)
    assert again == []
    assert again_keys == set()


def test_unchanged_tasks_kept():
    tasks = make_tasks()
    kept = unchanged_tasks(tasks, {"W-01"})
    assert [t.id for t in kept] == ["W-02"]
