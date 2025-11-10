# Pixiv 画师订阅插件

一个基于 HoshinoBot 的 Pixiv 画师订阅插件，支持自动推送订阅画师的最新作品到群聊。

## 功能特性

- **自动推送**：定时检查订阅画师的最新作品并推送到群聊
- **权限管理**：支持群管理员设置，普通用户只能查看
- **R18 控制**：可选择是否推送 R18 内容
- **标签屏蔽**：支持屏蔽包含特定标签的作品
- **多画质选择**：支持多种图片画质选项
- **智能过滤**：根据群设置智能过滤推送内容
- **批量推送限制**：防止连投时刷屏，可配置最大显示作品数量

## 更新记录

- 2025.10.14 添加了 `pixiv获取插画|pget` 命令
  - 可以使用插画的id获取指定插画, 并且有每日调用上限可在配置中修改
  - 修改了 `config.py`和`pixiv.py`两个文件
- 2025.11.11 让输入画师主页URL也可以订阅和取消订阅, pget可以使用URL获取插图
  - 修改了 `pixiv.py` 文件

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

# 每次推送时最多展示的作品数量
MAX_DISPLAY_WORKS = 3

# 图片画质选择
# 可选值: 'square_medium', 'medium', 'large', 'original'
# 注意: original 质量的图片体积较大，可能导致发送失败
IMAGE_QUALITY = 'large'

# 检查更新的时间间隔（小时）
CHECK_INTERVAL_HOURS = 3

# pixiv获取插画命令每日获取作品的上限
PGET_DAILY_LIMIT = 10 
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

## 使用指南

| 命令                             | 权限要求 | 说明                 |
|--------------------------------|------|--------------------|
| `pixiv订阅列表`                    | 所有用户 | 查看当前群的订阅列表         |
| `pixiv群设置`                     | 所有用户 | 查看当前群的设置状态         |
| `pixiv订阅画师 <画师ID/主页URL>`       | 管理员  | 通过画师id订阅指定画师       |
| `pixiv取消订阅 <画师ID/主页URL>`       | 管理员  | 取消订阅指定画师           |
| `pixiv获取插画\|pget <画师ID/主页URL>` | 所有用户 | 获取指定ID的插画（每日有调用上限） |
| `pixiv开启r18`                   | 管理员  | 本群允许推送 R18 内容      |
| `pixiv关闭r18`                   | 管理员  | 本群屏蔽 R18 内容        |
| `pixiv屏蔽tag <标签名>`             | 管理员  | 屏蔽包含指定标签的作品        |
| `pixiv取消屏蔽tag <标签名>`           | 管理员  | 取消屏蔽指定标签           |

### 超级用户命令

| 命令                       | 权限要求 | 说明                     |
|--------------------------|------|------------------------|
| `pixiv重设登录token <token>` | 超级用户 | 设置 Pixiv refresh_token |
| `pixiv强制检查`              | 超级用户 | 手动触发一次更新检查（测试用）        |

## 使用示例

### 订阅画师

```
# 订阅画师（需要知道画师的用户ID）例如: 用户https://www.pixiv.net/users/73798
pixiv订阅画师 73798
pixiv订阅画师 https://www.pixiv.net/users/73798

# 查看订阅列表
pixiv订阅列表

# 查看群设置
pixiv群设置

# 取消订阅
pixiv取消订阅 12345678

# 屏蔽标签 (tag应为pixiv上的日文标准标签)
pixiv屏蔽tag 巨乳
```

## 工作原理

1. **定时检查**：插件会根据 `CHECK_INTERVAL_HOURS` 设置的间隔时间自动检查订阅画师的新作品
2. **作品过滤**：根据每个群的设置（R18开关、屏蔽标签）过滤推送内容
3. **防刷屏**：当画师在检查间隔内发布多个作品时，最多只显示 `MAX_DISPLAY_WORKS` 个作品，其余以文字提示
4. **错误处理**：包含登录失效自动重试、网络异常处理等机制

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
├── refresh-token.json  # Pixiv 认证信息, 需要在这里填写 refresh_token
└── subscriptions.json  # 群组订阅数据以及设置（启动后自动生成）
```

## Future Plans

- 目前[插件列表](https://github.com/pcrbot/HoshinoBot-plugins-index)
  已经有[P站搜索](https://github.com/scofieldle/LeoBot/tree/main/hoshino/modules/pixiv_new)插件,
  提供了搜索画师作品和查看日月榜单等功能, 但是我加入的群中其实并没有太大的使用需求, 不清楚是否需要这个功能?
  如果有需要的话确实可以考虑将两个插件合并
- pixivpy3会通过`refresh_token`来获取`access_token`, 后续的请求都是携带`access_token`进行的, 但`access_token`
  的有效期只有[1+小时](https://github.com/upbit/pixivpy/issues/182), 所以在不做任何处理的情况下, 过一段时间后就会出现登陆失效的情况.
  目前采用的策略是直接进行api的请求, 如果发现请求失败则使用`api.login(refresh_token)`来重新登陆, 但是作为时长大于3小时的定时任务来说,
  每次必定会出现一次失败请求, 后续可以考虑优化一下这个地方

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个插件。

---

如有问题或建议，请在项目仓库中提交 Issue。