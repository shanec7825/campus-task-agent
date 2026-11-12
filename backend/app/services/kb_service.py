"""增量知识库（契约 `C-KB@1`，owner = T3）。

* :func:`index_task`：任务发布成功后增量入库（jieba 分词 + 停用词过滤 + ``extras`` 键名），
  按 ``task_id`` 幂等（先删旧行再插入）。
* :func:`find_similar`：**唯一打分公式**（plan `2.2.8`，禁止各自发明第二套）::

      q_tokens   = tokenize(q)
      entry_set  = set(tags) | set(tokenize(title))
      jaccard    = |q_set ∩ entry_set| / max(1, |q_set ∪ entry_set|)
      contain    = 1.0 if (q_norm in title_norm or title_norm in q_norm) else 0.0
      similarity = round(0.7 * jaccard + 0.3 * contain, 4)

  返回 ``similarity > 0`` 的前 ``top_n`` 条，按 ``similarity DESC, id DESC``。
  ``threshold`` 字段由路由层恒定为 0.6。
"""

from __future__ import annotations

import logging
from typing import Any

import jieba
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import KbEntry, Task
from app.schemas import SimilarItem

logger = logging.getLogger(__name__)

# 入库时 title + description 分词结果最多保留的词数
MAX_TAGS = 30

# description 前 N 字作为 summary
SUMMARY_LIMIT = 200

# 相似度阈值（契约恒定值；路由层据此做展示判断）
SIMILARITY_THRESHOLD = 0.6

# 中文常用停用词（仅过滤无实义词；业务词如"志愿/场地/招募"必须保留）
STOP_WORDS: frozenset[str] = frozenset(
    {
        "的",
        "了",
        "和",
        "与",
        "及",
        "以及",
        "或",
        "在",
        "是",
        "有",
        "没有",
        "不",
        "不是",
        "要",
        "需要",
        "必须",
        "可以",
        "能够",
        "会",
        "把",
        "被",
        "让",
        "给",
        "对",
        "对于",
        "关于",
        "通过",
        "按照",
        "根据",
        "从",
        "到",
        "向",
        "于",
        "为",
        "为了",
        "因为",
        "所以",
        "但是",
        "而且",
        "并且",
        "然后",
        "如果",
        "虽然",
        "这",
        "那",
        "这个",
        "那个",
        "这里",
        "那里",
        "这样",
        "那样",
        "我",
        "我们",
        "你",
        "你们",
        "他",
        "她",
        "它",
        "他们",
        "自己",
        "大家",
        "同学",
        "同学门",
        "一个",
        "一下",
        "一些",
        "什么",
        "怎么",
        "如何",
        "多少",
        "几个",
        "非常",
        "比较",
        "还是",
        "就是",
        "也是",
        "已经",
        "正在",
        "进行",
        "完成",
        "安排",
        "负责",
        "参加",
        "参与",
        "前往",
        "活动",
        "任务",
        "工作",
        "事情",
        "事情",
        "具体",
        "相关",
        "其他",
        "另外",
        "同时",
        "目前",
        "现在",
        "时候",
        "时间",
        "地点",
        "帮忙",
        "帮助",
        "请",
        "谢谢",
        "麻烦",
    }
)


def _norm(text: str | None) -> str:
    """归一化文本：小写、去空白（用于 contain 判定，不用于分词）。"""
    return "".join((text or "").lower().split())


def _is_stop(word: str) -> bool:
    return word in STOP_WORDS


def tokenize(text: str | None) -> list[str]:
    """分词 + 停用词/标点/纯数字过滤（去重保序，最多 :data:`MAX_TAGS` 个）。

    入库与检索共用**同一函数**（契约："同入库规则的分词与过滤"）。

    短查询（如"秋之韵"）即便被 jieba 切成单字也能通过"整串回退"保留一个 token，
    保证重叠打分不至于恒为 0；回退只发生在过滤后无任何有效 token 时。
    """
    raw_tokens = jieba.lcut(text or "")
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in raw_tokens:
        word = raw.strip()
        if len(word) < 2:
            continue
        if _is_stop(word):
            continue
        if word.isdigit():
            continue
        if not any(char.isalnum() for char in word):
            continue
        if word in seen:
            continue
        seen.add(word)
        tokens.append(word)

    if not tokens:
        fallback = _norm(text)
        if fallback and len(fallback) <= 30 and any(char.isalnum() for char in fallback):
            tokens.append(fallback)
    return tokens[:MAX_TAGS]


def _collect_tags(title: str, description: str | None, extras: dict[str, Any] | None) -> list[str]:
    """``tags = tokenize(title + " " + description)[:30] ∪ extras 的键名``（去重保序）。"""
    tags = tokenize(f"{title or ''} {description or ''}")
    for key in (extras or {}).keys():
        key_text = str(key).strip()
        if key_text and key_text not in tags:
            tags.append(key_text)
    return tags


def index_task(db: Session, task: Task) -> KbEntry:
    """为任务写入 / 覆盖一条知识库记录（按 ``task_id`` 幂等）。

    T2 在 ``POST /api/tasks`` 与子任务发布成功后调用；函数内部自行提交，
    因此调用方可以在任务已落库（拿到 ``task.id``）之后的任意时点调用。
    """
    if task.id is None:  # pragma: no cover - 防御性分支
        raise ValueError("index_task 需要已持久化的 task.id")

    description = (task.description or "")[:SUMMARY_LIMIT] or None
    tags = _collect_tags(task.title, task.description, task.extras or {})

    # 幂等：先删同 task_id 旧行，再插入
    db.execute(delete(KbEntry).where(KbEntry.task_id == task.id))
    entry = KbEntry(task_id=task.id, title=task.title, summary=description, tags=tags)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    logger.info("知识库入库: task_id=%s tags=%s", task.id, tags)
    return entry


def score_pair(q: str, entry: KbEntry) -> dict[str, Any]:
    """按**唯一公式**计算 (jaccard, contain, similarity)，供检索与自检打印。"""
    q_norm = _norm(q)
    q_tokens = tokenize(q)
    q_set = set(q_tokens)

    entry_tags = entry.tags if isinstance(entry.tags, list) else []
    entry_set = set(str(tag) for tag in entry_tags) | set(tokenize(entry.title))

    intersection = len(q_set & entry_set)
    union = max(1, len(q_set | entry_set))
    jaccard = intersection / union

    title_norm = _norm(entry.title)
    contain = 1.0 if (q_norm and title_norm and (q_norm in title_norm or title_norm in q_norm)) else 0.0

    similarity = round(0.7 * jaccard + 0.3 * contain, 4)
    return {
        "q_tokens": q_tokens,
        "entry_tokens": sorted(entry_set),
        "intersection": intersection,
        "union": union,
        "jaccard": round(jaccard, 4),
        "contain": contain,
        "similarity": similarity,
    }


def find_similar(
    db: Session,
    q: str,
    top_n: int = 3,
    min_similarity: float | None = None,
) -> list[SimilarItem]:
    """返回相似度降序的前 ``top_n`` 条。

    :param min_similarity: ``None`` 时按 plan `2.2.8` 原样返回 ``similarity > 0``
        的全部候选；传入阈值（路由层默认 0.6）时只保留 ``>= min_similarity`` 的条目。
    """
    query = (q or "").strip()
    if not query:
        return []

    entries = db.query(KbEntry).all()
    scored: list[tuple[int, SimilarItem]] = []
    for entry in entries:
        stats = score_pair(query, entry)
        similarity = stats["similarity"]
        if similarity <= 0:
            continue
        if min_similarity is not None and similarity < min_similarity:
            continue
        scored.append(
            (
                entry.id,
                SimilarItem(
                    task_id=entry.task_id,
                    title=entry.title,
                    summary=entry.summary,
                    similarity=similarity,
                    created_at=entry.created_at,
                ),
            )
        )

    # similarity DESC, id DESC
    scored.sort(key=lambda item: (item[1].similarity, item[0]), reverse=True)
    return [item[1] for item in scored[: max(1, top_n)]]


__all__ = [
    "MAX_TAGS",
    "SIMILARITY_THRESHOLD",
    "SUMMARY_LIMIT",
    "STOP_WORDS",
    "find_similar",
    "index_task",
    "score_pair",
    "tokenize",
]