# 发布 Windows EXE 与 Docker 版本

本工程使用 GitHub Actions 云端构建，不需要在本机安装 Windows、Docker 或 PyInstaller。发行文件是工作流在 Windows 上实际生成并运行验证的 EXE；配置文件本身不等于已有可下载的发行文件。

## 在网页上发布新版

1. 确保最新源码已推送到仓库的 main 分支，包括 `.github/workflows/release.yml`。如果推送提示账号或令牌失效，需要先在自己的 Git 客户端恢复登录；不要将令牌写进源码或聊天。
2. 打开仓库：https://github.com/xiaoyuyuan2006dx/SJTU-JunZhengMatch 。
3. 点击顶部 Actions，选择左侧 **Test and Release**。若提示尚未启用 Actions，按页面提示为此仓库启用。
4. 点击 **Run workflow**，分支选择 **main**。
5. 当前已发布v1.0.2；下一版在版本号输入框填尚未使用的 `v1.0.3`，然后点击运行。版本号留空时只验证和构建，不创建 Release。
6. 等待 test、windows、docker、release 全部显示成功。可以点进具体任务查看日志；release 要等前面的测试和两种构建都通过后才执行。
7. 回到仓库首页，进入右侧 Releases，打开本次填写的版本。Assets 中出现 EXE、ZIP、Docker归档和校验文件，才表示这一版发布完成。

发布使用工作流自身的 `GITHUB_TOKEN`，仅 release 任务授予 `contents: write`，不需要另外创建或保存个人访问令牌。若组织或仓库策略禁止写入，仓库管理员需检查 Actions 的工作流权限。

## 下载后如何使用

- Windows 用户下载 `JunZhengMatch.exe`，或解压 `SJTU-JunZhengMatch-Windows-x64.zip` 后双击同名 EXE。程序自动打开本机浏览器，无需 Python。
- EXE 内含737条公开教师记录，首次运行复制到用户可写目录。以后升级EXE继续使用已有库，不主动覆盖人工维护结果。
- Docker用户下载 `SJTU-JunZhengMatch-Docker.tar.gz`，用 `docker load -i` 导入，再按README配置访问密码和数据卷。
- GitHub自动提供的“Source code”ZIP只是源码，不是Windows可执行程序。
- 校验文件 `SHA256SUMS.txt` 对应同页的EXE、ZIP及Docker归档；Windows使用说明见 `WINDOWS.md`。

## 这条工作流具体做了什么

1. Ubuntu运行单元测试、内置自检、发布数据检查，并启动实际源码服务检查完整HTTP流程。
2. Windows x64安装Python 3.12及构建依赖，按 `JunZhengMatch.spec` 打包单文件、无控制台EXE。
3. 运行EXE的内置自检，再启动实际EXE服务，检查页面、文档、图片、公开教师库、六位虚构学生的十八个评审位置及CSV/XLSX导出。
4. Linux构建Docker镜像，执行匹配自检、启动容器并检查健康接口，最后保存镜像归档。
5. 汇总构建文件和校验值，创建草稿Release，附件上传完成后公开。对应版本号尚无标签时，发布任务将标签指向本次实际构建的提交。

Windows ZIP同时附带自检结果，便于核对实际构建过程。当前版本未使用商业代码签名。

## 以后发布新版

提交并推送修改到main，再按相同步骤填写新的版本号，例如 `v1.0.3`。不要把旧版本号用于另一份源码；工作流会拒绝覆盖指向不同提交的已有版本。历史版本保留，方便用户回退。

熟悉Git后，也可推送对应版本标签触发同一流程：

```bash
git tag v1.0.3
git push origin v1.0.3
```

## 构建失败时

打开对应Actions运行，查看第一个失败任务的日志。test失败先修复测试；windows失败查看打包或EXE自检步骤；docker失败查看镜像构建与容器日志。修复后推送，再发布新版本或重新运行尚未发布的同一提交。

如果前三个任务成功、只有release失败，通常应检查仓库写权限、版本号是否已指向其他提交或附件上传错误。工作流产物会保存在该次Actions运行的Artifacts中，便于排查；这些临时构建产物与公开Release附件是两个位置。
