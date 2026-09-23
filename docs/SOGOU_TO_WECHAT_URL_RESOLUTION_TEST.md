# 搜狗跳转到微信公众号原文 URL：公开访问测试

旧链接测试时间：2026-09-22T23:04:08.888490+08:00；来源批次：`2026-09-21_wechatmp02`。

## 已完成的3条旧链接测试

**到达真实微信域名：3/3；取得稳定、可再次访问的原文 canonical URL：0/3；出现验证码：0/3。**

三条均经有头 Chrome 正常导航进入 `mp.weixin.qq.com/s?src=11&timestamp=…&signature=…`，页面明确显示“链接已过期”。这些临时签名地址不能作为稳定 canonical URL，也没有可核验的文章正文。HTTP 200 和微信域名均不等于原文可用。

| 序号 | 公众号 | 标题 | 最终域名 | 稳定原文 URL | 验证码 | 结果 |
|---|---|---|---|---|---|---|
| 1 | 洮河管护中心 | 民族团结进步倡议书 | mp.weixin.qq.com | 未取得 | 未出现 | 链接已过期 |
| 2 | 广西人大 | 广西将组织实施首个民族团结进步宣传周活动 | mp.weixin.qq.com | 未取得 | 未出现 | 链接已过期 |
| 3 | 奉贤区二严寺 | 2026民族团结进步宣传周,促进民族团结进步,奋进伟大复兴征程. | mp.weixin.qq.com | 未取得 | 未出现 | 链接已过期 |

### 方法及失败阶段

- A：直接打开 JSONL 中保存的原始搜狗链接，浏览器正常运行页面并跳转；未修改 URL 参数、Cookie 或登录态。
- B：检查已加载页面的公开 DOM、canonical/og:url 以及 HTML 中字面量 URL。未取得稳定文章链接；HTML 中的 `${window.biz}` 等是未赋值的模板，不能当成真实 URL，也未尝试推导或解密。旧搜狗中间页自动跳走，未留存其完整 HTML，本次 DOM 结论限于实际取得的微信落地页。
- C：被动记录主框架导航及文档响应。每条均观测到搜狗 200 → 微信 200；未观测到可提供稳定地址的 302 Location。没有额外调用接口。
- 失败发生在微信文章落地阶段：签名地址到达微信，但微信仅返回过期提示，缺少可复用短链接或真实文章标识。
- 可自动记录跳转，但本次证据不能证明可稳定恢复原文。未达到至少2条有效原文的门槛，不实现或运行16条批量恢复。

### 每条原始地址与实际落地地址

#### 1. 洮河管护中心：民族团结进步倡议书

内容编号：`wxmp_31c94c996cb5ddfe6b83ea21`

原始搜狗 URL（公开结果原值）：

```text
https://weixin.sogou.com/link?url=dn9a_-gY295K0Rci_xozVXfdMkSQTLW6cwJThYulHEtVjXrGTiVgS1EhLTDWJRkHj_1mgzR8OkjqIEhoch9LZlqXa8Fplpd9bVeh49N6eWNBNtxBvgjG6-iGef6S6ECRoua0gnYm16FMMYo0hpaz3VnmizquOVA6q6jJhbUNLPRvljI-EXcZzs6FRzAVRSXSiMucfH3fkjET8MNGiP2aA3mdAdAqBA59ATXLYQQnOemBQZ49c5lVufSUNJ884SzEXslC06AvLuhQL0Hr9Gyd3Q..&type=2&query=%E6%B0%91%E6%97%8F%E5%9B%A2%E7%BB%93%E8%BF%9B%E6%AD%A5%E5%80%A1%E8%AE%AE&token=5B4D10FD1BEEFCAF7375288DE587ECDB742750416AB1384D
```

实际落地 URL（已过期，不作为 canonical）：

```text
https://mp.weixin.qq.com/s?src=11&timestamp=1789999181&ver=6980&signature=hNsqMT7uSdN4sWsa-mBZPc00bJklPFNlTipA6O0n*q0W3DDzwKBP47XICtyo3MHA8FWet6jj2INod8sEx0LbDKaGy-MV*fELqEtTK371CB-aH07L*DsXmnH8UHOBdjoO&new=1
```

#### 2. 广西人大：广西将组织实施首个民族团结进步宣传周活动

内容编号：`wxmp_5162cb813075d2768ecca2b6`

原始搜狗 URL（公开结果原值）：

```text
https://weixin.sogou.com/link?url=dn9a_-gY295K0Rci_xozVXfdMkSQTLW6cwJThYulHEtVjXrGTiVgS1EhLTDWJRkH0nYtOW64GELqIEhoch9LZlqXa8Fplpd922yGyCAXG8r7zxDke1OQj7xk0e0jF6O7h5-MfuaQSCrT6YgC4Z7oeYKyzNUooOawaLwW0LKc57BRgJhVB8rokQqnY5SFdssRm5Ka2JnzNj6Gg5GV8B4I7po6LLBytK4W-p3SChxecx6Y26Wabb_D6nucDDPeaRmqcLvU3zpazgMY-UZGbO56rA..&type=2&query=2026%E5%B9%B4%E6%B0%91%E6%97%8F%E5%AE%A3%E4%BC%A0%E5%91%A8%E4%B8%BB%E5%9C%BA%E6%B4%BB%E5%8A%A8&token=5B4DC34A1BEEFCAF7375288DE587ECDB742750416AB1386A
```

实际落地 URL（已过期，不作为 canonical）：

```text
https://mp.weixin.qq.com/s?src=11&timestamp=1789999210&ver=6980&signature=b7eunfeDlR5NjvgBfZOuungD3Wuc47lYt5WvdLvcND5Tu4TJF9nNBxmA76YYT-iH*aDAo0PJsWuTUpLvmR5k2j9G0o0R6zvGSYP8w7JyuWWRukUNJLtRtOel1Nywv4uk&new=1
```

#### 3. 奉贤区二严寺：2026民族团结进步宣传周,促进民族团结进步,奋进伟大复兴征程.

内容编号：`wxmp_7e11225a19f36430b36f8cf9`

原始搜狗 URL（公开结果原值）：

```text
https://weixin.sogou.com/link?url=dn9a_-gY295K0Rci_xozVXfdMkSQTLW6cwJThYulHEtVjXrGTiVgS1EhLTDWJRkHZJz00OVAcjfqIEhoch9LZlqXa8Fplpd95MQM8_HG_STBfgfgZ6VbTWhvucOTkgB5tZewpJqe_f1p0M5tgeAnQo0jbBni2MTanQcBM0F57S9aTKL6o8m9443ZTnNdTaGA9dFR17N2IMh0Z5HwdKdVI7APM5tz7hUlPxxrimyZ7WdGyKd8cv0KgoyI_9JZV-V4zULjbLDzZe_2CsG6-xMgzQ..&type=2&query=%E4%BF%83%E8%BF%9B%E6%B0%91%E6%97%8F%E5%9B%A2%E7%BB%93%E8%BF%9B%E6%AD%A5%EF%BC%8C%E5%A5%8B%E8%BF%9B%E4%BC%9F%E5%A4%A7%E5%A4%8D%E5%85%B4%E5%BE%81%E7%A8%8B&token=5B4ED2411BEEFCAF7375288DE587ECDB742750416AB13895
```

实际落地 URL（已过期，不作为 canonical）：

```text
https://mp.weixin.qq.com/s?src=11&timestamp=1789999253&ver=6980&signature=V813hogaNdLI*NXTMTi9a*VJ*o7PhMm25FCa1wTeE*cFzUcxQU3XKF4DE6iqfnJfXymeebPWi0l5f27vFZXXh6hINIAihi3KrCidqNWwUQVzvMVrkAVF-SGgxFyNP0DZ&new=1
```

## 已保存 HTML 检查（离线）

共检查 5 个显式保存的 HTML 文件；未读取或逆向浏览器缓存、Cookie、存储或登录凭据。

| 文件 | 字面量微信 URL 数量 |
|---|---|
| `data/wechat_mp/2026-09-21_wechatmp02/debug/footer_1.html` | 0 |
| `data/wechat_mp/2026-09-21_wechatmp02/debug/footer_2.html` | 0 |
| `data/wechat_mp/2026-09-21_wechatmp02/debug/footer_3.html` | 0 |
| `data/wechat_mp/2026-09-21_wechatmp02/debug/footer_4.html` | 0 |
| `data/wechat_mp/debug/footer_1.html` | 0 |

这些文件为搜狗结果卡片的来源/时间 footer 调试片段，保存时主动移除了链接等属性，不是完整搜索结果 HTML。未发现可用原文 URL，不能据此宣称完整原网页不存在链接。

## 1条重新公开定位测试

目标：广西人大《广西将组织实施首个民族团结进步宣传周活动》。

查询：`广西将组织实施首个民族团结进步宣传周活动 广西人大`；只访问这一次精确查询的第一页，不翻页。

搜索状态：`NO_STABLE_ARTICLE_URL`；验证码：未出现。

可用且再次访问验证成功的稳定 URL：否。

结果说明：新鲜搜索结果正常点击后仍未取得稳定 canonical URL，停止继续尝试。

搜索最终页面：`https://weixin.sogou.com/weixin?type=2&query=%E5%B9%BF%E8%A5%BF%E5%B0%86%E7%BB%84%E7%BB%87%E5%AE%9E%E6%96%BD%E9%A6%96%E4%B8%AA%E6%B0%91%E6%97%8F%E5%9B%A2%E7%BB%93%E8%BF%9B%E6%AD%A5%E5%AE%A3%E4%BC%A0%E5%91%A8%E6%B4%BB%E5%8A%A8+%E5%B9%BF%E8%A5%BF%E4%BA%BA%E5%A4%A7`

搜索结果卡片数：10；标题与公众号同时精确匹配数：1。

文章最终地址：`https://mp.weixin.qq.com/s?src=11&timestamp=1790090620&ver=6982&signature=jsD-*NqhzSibhPAIDCK3a43qEn7bnE3PLwvXAdqPCBEgJ19DfX1FYbo67PSs58Zb72RjkZfLYcWPhawGl3RwTzXxsvnqspveACdie2PlBQuss3BeqD*Cfk9*rJsO*1ZC&new=1`

页面可见证据（节选）：广西将组织实施首个民族团结进步宣传周活动
广西人大
 2026年9月21日 16:50 广西

　　2026年3月12日，十四届全国人大四次会议高票通过《中华人民共和国民族团结进步促进法》，其中第五十六条规定：每年9月的第四周为民族团结进步

本次精确定位找到了唯一匹配文章，正常点击后能够阅读真实正文；这与旧链接的过期提示不同。但地址栏仍为带 timestamp/signature 的临时地址，canonical/og:url 未提供稳定 URL。没有稳定候选，所以未进行稳定 URL 再次访问验证，也不将“正文可读”计为 canonical 恢复成功。

**结论：旧搜狗临时跳转链接无法稳定恢复原文URL。** 本次3条旧链接与1次重新公开定位未验证出免费批量恢复能力，已经停止继续尝试；这不代表所有新鲜搜狗链接永远无法使用。

最现实的下一步：人工在微信中打开对应文章，通过“复制链接”收集真实原文 URL；已有的人工提供广西人大短链接应单独标记为人工来源，不计入本次解析成功。取得真实链接后，再由用户决定是否花费剩余 SocialDataX 积分。本轮不调用该服务。

## 数据与调用边界

- SocialDataX 调用：0；本轮 SocialDataX 积分消耗：0（未访问账户余额接口）。
- 无完整关键词搜索、无临时签名破解、无验证码绕过、无非公开微信接口调用。
- 批次目录19个普通文件 SHA-256 前后一致，包含原始 JSONL、两版 XLSX、CSV、POMS JSON；Excel 临时锁文件不在检查范围内。
- 未 commit、未 push。

本地证据：`data/wechat_mp/sogou_url_probe/results.json` 保留初始导航观测；其中早期 RESOLVED 仅判断域名和路径，不能作为业务结论。`assessed_results.json` 已将三条重新离线判定为 EXPIRED_SIGNED_LINK、canonical=null、有效数量0。未因此重新发起网络请求。

`probe_three.py` 已完成判定修正；已有结果存在时拒绝重复运行。调试脚本和证据均位于已被 git 忽略的 data/wechat_mp 下，不修改正式采集或导出代码。
