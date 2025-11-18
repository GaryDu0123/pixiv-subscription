# Pixiv 插画推送插件

一个基于 HoshinoBot 的 Pixiv 插件，包含 **画师订阅** 和 **Pixiv工具** 两个独立的服务，支持自动推送、作品预览、pixiv排行榜查询等功能。

## 功能特性

### Pixiv 画师订阅 (`pixiv-subscription`)
- **自动推送**: 定时检查订阅画师的最新作品并推送到群聊。
- **权限管理**: 支持群管理员设置订阅、屏蔽规则等。
- **R18 控制**: 可选择是否推送 R18 内容。
- **标签屏蔽**: 支持屏蔽包含特定标签的作品。
- **智能过滤**: 根据每个群的设置智能过滤推送内容。

### Pixiv 工具 (`pixiv-tools`) - <font color="red">默认关闭</font>
- **作品预览**: 通过画师id或者URL预览画师最新作品。
- **作品获取**: 通过作品ID或URL获取指定插画。
- **排行榜**: 获取Pixiv日、周、月、男性向、女性向、原画等多种排行榜。
- **防刷屏**: 排行榜和画师预览默认使用合并转发消息，避免刷屏。

## 更新记录

- **2025.11.18 插件拆分为 `pixiv-subscription` 和 `pixiv-tools` 两个服务**
  - 将 `pget` 命令从`pixiv-subscription` 移动到 `pixiv-tools` 服务中
  - 修改了 `pixiv.py` 文件, 新增 `pixiv_tools.py` 文件
- **2025.11.11 让输入画师主页URL也可以订阅和取消订阅, pget可以使用URL获取插图**
  - 修改了 `pixiv.py` 文件
- **2025.10.14 添加了 `pixiv获取插画|pget` 命令**
  - 可以使用插画的id获取指定插画, 并且有每日调用上限可在配置中修改。
  - 修改了 `config.py`和`pixiv.py`两个文件。

## 安装配置

### 1. 安装与配置

* 安装必要的依赖库：
    - 依赖库：
      ```bash
      pip install -r requirements.txt
      ```
    - 或者手动安装：
      ```bash
      pip install pixivpy3==3.7.5 aiohttp
      ```
* 下载或者clone本插件项目，并将`pixiv-subscription` 文件夹放入 HoshinoBot 的 `modules` 目录下。
* 在 `MODULES_ON` 列表中，添加 `pixiv-subscription` 并重启 HoshinoBot 使配置生效

### 2. 配置说明

在 `config.py` 中进行配置：

```python
# 代理设置（可选）
PROXY_URL = None  # 例如: "http://127.0.0.1:10808"

# 每次推送时最多展示的作品数量，当画师连投（检查时间间隔内发布多个独立作品）时生效，多图作品仅展示首图
MAX_DISPLAY_WORKS = 3

# 可选值: 'square_medium', 'medium', 'large', 'original' (可以大致理解为从小到大)
# 注意: original质量的图片体积较大，可能导致发送失败
IMAGE_QUALITY = 'large'

CHECK_INTERVAL_HOURS = 3  # 检查更新的时间间隔，单位为小时

# 单用户pixiv获取插画命令每日获取作品的上限
PGET_DAILY_LIMIT = 10  

# 单用户预览画师信息命令每日使用上限
PREVIEW_ILLUSTRATOR_LIMIT = 10  

# 是否启用合并转发回复模式
CHAIN_REPLY = True  

# 每次推送排行榜时最多展示的作品数量
RANK_LIMIT = 5  

# 是否启用“推送机器人账号关注的画师”功能
# 开启后，各群管理员才能通过指令选择是否接收推送
# 出于隐私和性能考虑，默认关闭
ENABLE_FOLLOWING_SUBSCRIPTION = False
```

### 3. 使用`pixiv_auth.py`获取 Pixiv Refresh Token

1. 下载并运行认证脚本：

    ```
    bash python pixiv_auth.py login
    ```
   脚本会自动打开浏览器进入Pixiv登录页面
2. 打开开发者工具(F12)，切换到网络(Network)标签页
3. 启用持久日志记录 ("Preserve log")
4. 在过滤器字段中输入：callback?
5. 完成Pixiv登录流程
6. 登录成功后，你会看到一个空白页面和类似这样的请求：
   https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?state=...&code=...
   复制code参数的值到脚本提示中并按回车

   如果操作正确，会显示auth_token和refresh_token

   > ⚠️ 注意：code的有效期极短，请尽量减少步骤5和6之间的延迟。如果失败，请从步骤1重新开始。

7. 将获取到的 `refresh_token` 填入 `refresh-token.json` 文件中
    ```json
    {
      "refresh_token": "你的_refresh_token_值"
    }
    ```
   更多信息请参考 [pixivpy3 仓库](https://github.com/upbit/pixivpy),
   以及 [@ZipFile Pixiv OAuth Flow](https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362)

## Service使用指南

### Pixiv 画师订阅 (`pixiv-subscription`)

此服务默认开启，主要用于自动推送画师更新。

| 命令                       | 权限要求 | 说明             |
|:-------------------------|:-----|:---------------|
| `pixiv订阅列表`              | 所有用户 | 查看当前群的订阅列表     |
| `pixiv群设置`               | 所有用户 | 查看订阅相关的群设置     |
| `pixiv订阅画师 <画师ID/主页URL>` | 管理员  | 订阅指定画师         |
| `pixiv取消订阅 <画师ID/主页URL>` | 管理员  | 取消订阅指定画师       |
| `pixiv开启r18`             | 管理员  | 本群允许推送 R18 内容  |
| `pixiv关闭r18`             | 管理员  | 本群屏蔽 R18 内容    |
| `pixiv屏蔽tag <标签名>`       | 管理员  | 屏蔽包含指定标签的作品    |
| `pixiv取消屏蔽tag <标签名>`     | 管理员  | 取消屏蔽指定标签       |
| `pixiv开启关注推送`            | 管理员  | 订阅机器人账号关注的全部画师 |
| `pixiv关闭关注推送`            | 管理员  | 取消订阅机器人账号关注的画师 |

#### 超级用户命令

| 命令                       | 权限要求 | 说明                     |
|:-------------------------|:-----|:-----------------------|
| `pixiv重设登录token <token>` | 超级用户 | 设置 Pixiv refresh_token |
| `pixiv强制检查`              | 超级用户 | 手动触发一次订阅更新检查（测试用）      |

### Pixiv 工具 (`pixiv-tools`)

**注意: 此服务默认关闭，手动在需要群中开启**

| 命令                             | 权限要求 | 说明         |
|:-------------------------------|:-----|:-----------|
| `pixiv预览画师 <画师ID/主页URL>`       | 所有用户 | 预览画师最新作品   |
| `pixiv获取插画\|pget <作品ID/作品URL>` | 所有用户 | 获取指定ID的插画  |
| `pixiv日榜`                      | 所有用户 | 获取插画日榜     |
| `pixiv周榜`                      | 所有用户 | 获取插画周榜     |
| `pixiv月榜`                      | 所有用户 | 获取插画月榜     |
| `pixiv男性向排行`                   | 所有用户 | 获取男性向插画排行榜 |
| `pixiv女性向排行`                   | 所有用户 | 获取女性向插画排行榜 |
| `pixiv原画榜`                     | 所有用户 | 获取原画榜      |

## 注意事项

- ⚠️ refresh_token 为账号的登录凭证，请妥善保管, 不要上传到公共仓库, 不清楚频繁请求会不会账号收到限制, 目前未发现有这种情况
- refresh_token的过期时间较长, 没有明确的过期时间, 但如果发现bot出现登录失败, 可以尝试重新获取并更新token
- 图片质量选择`original`质量时文件较大，可能导致发送失败

## 文件结构

```
pixiv-subscription/
├── config.py           # 配置文件
├── requiements.txt     # 依赖列表
├── pixiv_auth.py       # 用于获取refresh_token的脚本
├── pixiv_tools.py      # pixiv-tools服务主文件
├── pixiv.py            # pixiv-subscription服务主文件
├── refresh-token.json  # Pixiv 认证信息, 需要在这里填写 refresh_token
└── subscriptions.json  # 群组订阅数据以及设置（启动后自动生成）
```

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个插件。
