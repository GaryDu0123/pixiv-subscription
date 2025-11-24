#!/usr/bin/env python
# -*-coding:utf-8 -*-
import asyncio
from typing import List, Union
from hoshino.typing import CQEvent
from hoshino.config import NICKNAME
from .config import CHAIN_REPLY


def _build_forward_nodes(bot, user_id: str, messages: List[str]):
    """构造合并转发节点数据"""
    bot_name = str(NICKNAME[0] if NICKNAME else "Bot")
    return [
        {
            "type": "node",
            "data": {
                "name": bot_name,
                "user_id": str(user_id),
                "content": str(msg)
            }
        }
        for msg in messages
    ]

async def send_messages(bot, ev: CQEvent, messages: List[str]):
    """
    向事件来源发送消息列表
    """
    if not messages:
        return

    # 1. 如果开启了合并转发，且是群消息
    if CHAIN_REPLY and getattr(ev, 'detail_type', '') == 'group':
        nodes = _build_forward_nodes(bot, ev.self_id, messages)
        try:
            await bot.send_group_forward_msg(group_id=ev.group_id, messages=nodes)
            return
        except Exception:
            # 如果合并转发发送失败（如风控），回退到下面的逐条发送
            pass

    # 2. 逐条发送 (Fallback 或 CHAIN_REPLY=False)
    for msg in messages:
        await bot.send(ev, msg)
        await asyncio.sleep(2)


async def send_to_group(bot, group_id: int, messages: List[str]):
    """
    直接向指定群发送消息列表。
    适用于不在事件响应函数内的场景。
    """
    if not messages:
        return

    # 确保 group_id 是整数
    gid = int(group_id)

    # 1. 合并转发模式
    if CHAIN_REPLY:
        # 定时任务没有 ev，直接用 bot.self_id
        nodes = _build_forward_nodes(bot, bot.self_id, messages)
        try:
            await bot.send_group_forward_msg(group_id=gid, messages=nodes)
            return
        except Exception as e:
            pass

    # 逐条发送模式
    for msg in messages:
        await bot.send_group_msg(group_id=gid, message=msg)
        await asyncio.sleep(2)