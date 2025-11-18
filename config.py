# 示例 PROXY_URL = "http://127.0.0.1:10808"
PROXY_URL = None

# 每次推送时最多展示的作品数量，当画师连投（检查时间间隔内发布多个独立作品）时生效，多图作品仅展示首图
MAX_DISPLAY_WORKS = 3

# 可选值: 'square_medium', 'medium', 'large', 'original' (可以大致理解为从小到大)
# 注意: original质量的图片体积较大，可能导致发送失败
IMAGE_QUALITY = 'large'

CHECK_INTERVAL_HOURS = 3  # 检查更新的时间间隔，单位为小时

PGET_DAILY_LIMIT = 10  # 单用户pixiv获取插画命令每日获取作品的上限

PREVIEW_ILLUSTRATOR_LIMIT = 10  # 单用户预览画师信息命令每日使用上限

CHAIN_REPLY = True  # 是否启用合并转发回复模式

RANK_LIMIT = 5  # 每次推送排行榜时最多展示的作品数量

# 是否启用“推送机器人账号关注的画师”功能
# 开启后，各群管理员才能通过指令选择是否接收推送
# 出于隐私和性能考虑，默认关闭
ENABLE_FOLLOWING_SUBSCRIPTION = False