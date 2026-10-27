# 上传代码与发布版本

## 上传代码

使用 GitHub Desktop 打开本仓库的本地文件夹，检查 Changes 中的改动，填写提交说明并点击 Commit，再点击 Push origin。学生原表、个人运行目录、密码或令牌不要提交；仓库自带的公开教师种子库可以提交。

也可使用 Git：

```bash
git add .
git commit -m "说明本次修改"
git push origin main
```

上传源码不会自动公开一个新 Release；main 推送会执行构建验证。

## 网页发布

1. 打开仓库的 **Actions → Test and Release → Run workflow**。
2. 选择已上传的分支。版本号留空可先构建验证，不发布。
3. 验证通过后重新运行，填写未使用的版本号，例如 `v1.1.0`；后续修复可用 `v1.1.1`。
4. 等待 test、windows、docker、release 全部成功。
5. 到 **Releases** 查看版本和附件。工作流先创建草稿，附件完整上传后公开。

`probe_installer` 仅用于诊断已发布的安装包，正常构建或发布时保持关闭。

无需本地 Windows 或 Docker，也无需手动上传 EXE。发布使用 GitHub 自动提供的工作流令牌，不要将个人令牌放入工程。版本号不能复用到不同提交。

## 标准发行文件

- `JunZhengMatch-版本-windows-x64-portable.zip`：浏览器版EXE、说明、验证报告。
- `JunZhengMatch-版本-windows-x64-setup.msi`：独立窗口安装版，选择外部数据位置。
- `JunZhengMatch-版本-docker-amd64.tar.gz`：可导入的镜像。
- `SHA256SUMS.txt`：以上三个文件的校验值。

GitHub自动生成的 Source code 仅为源码。Windows安装与使用见 [WINDOWS.md](WINDOWS.md)。历史版本保留，方便回退。

## 发布前检查

```bash
python -m pip install -r packaging/requirements-dev.txt
python tools/run_tests.py --report tests-report.json
python packaging/launcher.py --self-test --report self-test.json
python tools/privacy_check.py
python tools/verify_app.py --report http-self-test.json
python tools/verify_runtime.py --report runtime-test.json
```

Windows原生构建后还检查EXE图标、独立窗口和后台共享；MSI实际安装、运行、卸载并验证数据保留。失败时先看Actions中第一个失败步骤及诊断附件，修复推送后重新验证。只有发布步骤失败时，检查工作流写权限、版本标签和上传错误。
