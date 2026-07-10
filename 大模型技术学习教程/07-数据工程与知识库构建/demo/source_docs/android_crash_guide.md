---
id: android-crash-guide
title: Android 崩溃排查知识
source_uri: app://knowledge/android/crash
tags: android, crash, logcat
version: v1
owner: mobile-team
---

# Android 崩溃排查知识

NullPointerException、IllegalStateException、IndexOutOfBoundsException 是 Android 项目中常见的崩溃类型。
排查时先看 FATAL EXCEPTION 所在线程，再看 Caused by、业务堆栈、最近发布版本和用户操作路径。
如果崩溃只发生在页面切换、后台恢复或权限弹窗后，要重点检查 Activity 生命周期、Fragment 状态保存和异步回调是否越界访问 UI。
知识库条目应保留崩溃类型、影响版本、复现步骤、修复提交和验证方式。
