# 阅读器视觉规范与本地预览

公开阅读器的首页、新闻纵览、新闻详情共用 `geist-tokens.css` 和 `tailwind-geist-preset.ts`。React、shadcn/Radix 组件和 API 契约保持兼容；管理后台也引用这些共享颜色 token。

## 本地查看

已有依赖时，在仓库根目录运行：

```sh
npm run dev:preview
```

打开 `http://127.0.0.1:5173/public-app/`。新闻纵览为 `/public-app/?channel=all`；示例详情为 `/public-app/events/preview-1?target_id=italy`。顶栏可切换浅色、深色、跟随系统；列表可搜索和筛选，详情可返回新闻流。

也可使用已有静态预览命令：

```sh
npm run build:preview --prefix frontend/public
npm run preview:preview --prefix frontend/public
```

此时端口为 5174。预览模式显示“本地预览 · 示例内容”，只使用 `frontend/public/src/preview/local-preview.ts` 中的虚构样例；所有 `fetch` 在浏览器内响应，未知端点和写入返回 404，不连接后台。普通 `npm run build` 不包含预览数据。预览构建输出到 `frontend/public/dist-preview/`，不会覆盖生产构建的 `dist/`。

## 原则与 token

| 原则 | 决定 |
| --- | --- |
| 色板封顶 | 金色 `primary`；单条纯灰阶；仅成功、警告、危险三个语义色；`info`、`feature` 兼容别名使用中性色 |
| 信息层级 | 页面/热点新闻标题 24–32px、主新闻/详情标题 24–40px、普通卡片标题 16–20px、段落 15–17px、元信息 12–14px；首页栏目名使用 `text-meta` / 500，主新闻使用 `text-lead` / 600，热点新闻使用 `text-title` / 700 |
| 间距层级 | `gutter` 16–40px、`section` 24–48px、`stack` 12–20px；无需通过多色分组 |
| 全宽工作区 | 1024px 起为侧栏加 `minmax(0,1fr)`；768px 保留地区快选；小于 768px 默认只显示紧凑已选条件与筛选按钮，完整地区/议题/相关列表进入 Radix 抽屉；1600px 起时间线双列 |
| 标签与关联 | 列表卡片合并地区和标签后按显示文本去重，标题上方最多 2 个标签，分值用普通元信息；详情关联三栏 `items-start`、列内 `content-start`，空状态随内容收缩 |
| 移动端底栏 | 底栏高度为 `--mobile-navigation-height`（4.25rem）加安全区；`main` 底部 padding 再加 `gutter`，页面滚动留白也计入安全区；1024px 起还原桌面间距 |
| 文章可读性 | 页面使用全部可用宽度，正文限制 78ch，来源与研判信息放在邻栏；窄屏按阅读顺序堆叠 |
| 焦点与触控 | 统一 2px `ring` 轮廓、默认 3px 外间距；贴近裁切边界的中性控件用 `focus-inset` 将 offset 调为 -3px；滚动容器预留 6px 焦点空间；按钮/输入框至少 44px；抽屉与图片预览支持 Escape 和焦点恢复 |
| 已读与暗色 | 已读显示文字，不降低整条新闻透明度；暗色表面使用灰阶明度，文字保持对比度 |

颜色数值只写在共享 token 文件。组件使用 shadcn 语义类或 CSS 变量，不引入新的颜色字面量。焦点环落在中性表面；`focus-inset` 只用于中性填充的候选项、信源行、已选条件和 Sheet 自身，不用于主色按钮。CardContent 和来源新闻列表不裁切外环；其余保留裁切的内容容器须留足 5px（2px 轮廓 + 3px offset）空间。默认边框仅用于分组；输入框边界使用更强的 `input` token。

验证使用 `npm test`、`npm run build`；本次本地验收记录位于忽略目录 `.redesign-evidence/`，不随提交分发。浏览器无法运行时，截图、断点无溢出与实际 Tab 顺序必须明确记为未实测。
