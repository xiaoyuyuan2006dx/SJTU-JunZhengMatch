# 图片与图标来源

页面使用用户选定并提供的藤田琴音图片，均原样复制，不改动画面内容。角色及图片权利归各自权利人；未确认原始发布地址，不作额外作者署名。

- `src/junzheng_match/web/kotone-portrait.jpg`：左侧立绘。
- `src/junzheng_match/web/kotone-mascot.png`：右下小人。
- `src/junzheng_match/web/kotone-scene.png`：底层场景，CSS控制不透明度、位置和顶部渐隐。
- `src/junzheng_match/web/kotone-exit.png`：用户提供的透明底完整退出贴纸，整张可点击，无方形悬浮阴影。
- `src/junzheng_match/web/kotone-sign.png`：保留原始签名素材，当前右上使用完整退出贴纸。

两侧人物不透明度为100%，通过缩放和正片叠底融入留白，不接收鼠标点击。窄屏隐藏侧边人物；退出按钮始终可操作。图片随程序打包，无需联网加载。

## Windows程序图标

用户提供的圆形琴音原图为 `assets/app-icon.png`。`assets/app.ico` 编码了16、24、32、48、64、128、256像素七种尺寸，保留透明通道；构建时嵌入EXE资源，无需另放ICO文件。CI核对内嵌图像负载与原ICO一致。

## 安装引导插图

用户提供的樱花琴音图片原件保存在 `assets/installer-art.png`，安装背景由 `packaging/windows/installer-background.html` 组合原图、薄荷绿／樱粉渐变及奶油色面板。构建时渲染为 `build/installer-background.bmp` 嵌入MSI，右侧立绘渐隐融入背景，不联网加载。原图不改动。

## 微软运行组件

MSI 随附 Microsoft WebView2 Evergreen x64 完整离线安装器，构建时从微软下载并验证数字签名，保留原文件及微软许可。该组件适用微软自身的许可，不属于本项目代码许可证的授权范围。分发方式见[微软 WebView2 分发说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution#offline-deployment)。已有运行环境时跳过安装；浏览器便携版不需要此组件。
