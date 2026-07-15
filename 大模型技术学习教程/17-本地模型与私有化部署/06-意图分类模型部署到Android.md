# 意图分类模型部署到 Android

阶段 16 已经完成意图分类的训练、validation 校准和 JSON 制品导出。本章只处理部署边界：用 Python 生成一次制品，再让纯 Java 和 Android 加载同一份制品做离线推理。

先阅读 [意图识别与分类训练实战](../16-微调与模型定制/05-意图识别与分类训练实战.md)。本章不创建完整 Android Studio 工程，不展开 UI、Gradle、Manifest 或网络框架，只保留可编译命令和核心集成代码。

## 1. 核心文件与边界

Java 示例包含四个 package-free 文件：

- [MiniJson.java](./demo/android/MiniJson.java)：解析固定 JSON schema。
- [IntentModelLoader.java](./demo/android/IntentModelLoader.java)：读取、校验并构造不可变模型。
- [MobileIntentClassifier.java](./demo/android/MobileIntentClassifier.java)：规范化、n-gram、概率和拒识推理。
- [MobileIntentClassifierTest.java](./demo/android/MobileIntentClassifierTest.java)：加载、损坏制品、资源边界和推理测试。

这些核心类不依赖 Android Framework，也不需要第三方机器学习 Runtime，因此可以先用 JDK 命令行验证。package-free 是为了让教程中的 `javac` 命令直接运行；复制到真实 App 时，可以给四个文件统一添加应用包名。

模型不包含 Python 代码，只包含标签、阈值和朴素贝叶斯统计量。Java 必须复现 Python 的候选排序与拒识顺序，不能在端侧另写一套“差不多”的逻辑。

## 2. 从 Python 导出到 Java 的 fresh smoke test

下面命令都在仓库根目录运行。先把新模型导出到 `$env:TEMP`：

```powershell
$demo = '.\大模型技术学习教程\16-微调与模型定制\demo\intent_classifier_demo.py'
$data = '.\大模型技术学习教程\16-微调与模型定制\demo\sample_intents.jsonl'
$model = Join-Path $env:TEMP 'intent-model.json'
Remove-Item -ErrorAction SilentlyContinue -LiteralPath $model
python $demo train --data $data --model $model --model-version 'tutorial-v1'
```

每次编译都创建一个 fresh `$out`，避免旧 `.class` 掩盖漏编文件：

```powershell
$src = '.\大模型技术学习教程\17-本地模型与私有化部署\demo\android'
$out = Join-Path $env:TEMP ('intent-java-classes-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $out | Out-Null

javac -encoding UTF-8 -d $out `
  "$src\MiniJson.java" `
  "$src\IntentModelLoader.java" `
  "$src\MobileIntentClassifier.java" `
  "$src\MobileIntentClassifierTest.java"
```

先运行 Java 测试：

```powershell
java -cp $out MobileIntentClassifierTest $model
```

成功时最后一行是：

```text
MobileIntentClassifierTest OK
```

再用同一个 `$model` 预测：

```powershell
java -cp $out MobileIntentClassifier --model $model --text '帮我取消订单'
```

输出是 UTF-8 JSON，`intent` 和 `reason` 应分别为 `cancel_order`、`accepted`。如果编译或运行失败，不要换一份模型绕过问题；先确认 Python 导出的文件、四个 Java 源文件和测试都来自同一提交。

## 3. Windows 上的 strict UTF-8 `--text-file`

普通 ASCII 和当前终端能正确传递的中文仍可使用 `--text`。但 Windows 原生 Java launcher 接收命令行参数时会经过系统代码页；代码页之外的字符可能在进入 Java 前已经丢失，JVM 内部再转 UTF-8 也无法恢复。

涉及 emoji、补充平面字符或需要逐字节复现的 parity 输入时，使用 `--text-file`。下面命令写入无 BOM UTF-8，并主动检查没有 BOM：

```powershell
$textFile = Join-Path $env:TEMP 'intent-input-utf8.txt'
$utf8NoBom = [Text.UTF8Encoding]::new($false, $true)
[IO.File]::WriteAllText($textFile, '订单ID2026😀', $utf8NoBom)

$bytes = [IO.File]::ReadAllBytes($textFile)
if ($bytes.Length -ge 3 -and
    $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
  throw 'unexpected UTF-8 BOM'
}

java -cp $out MobileIntentClassifier --model $model --text-file $textFile
```

`--text` 与 `--text-file` 必须二选一。文件通道使用严格 UTF-8 解码：非法字节、空白文件或超过 1 MiB 都会返回 `text_load_failed`，不会使用系统默认编码偷偷回退。

## 4. 为什么同一 artifact 与同一 parity cases 很重要

跨端验收使用阶段 16 的 [同一份 parity cases](../16-微调与模型定制/demo/intent_parity_cases.jsonl)。测试过程是：

```text
Python 训练一次并导出 artifact
-> Python 重新加载 artifact 后预测
-> Java 加载同一 artifact 后预测
-> 对同一组 cases 比较结果
```

判定标准不只看最终标签：

1. `intent` 和 `reason` 必须完全相同。
2. `candidates` 的 intent 顺序必须完全相同。
3. 每个 probability、confidence 和 margin 的绝对误差不超过 `1e-9`。
4. `no_features`、`low_confidence`、`low_margin` 三条拒识路径都要覆盖。

这样能发现“最终标签碰巧相同，但概率、排序或阈值边界已经漂移”的问题。Python 测试会自动生成新 artifact、fresh 编译 Java，再逐条执行这些 cases。

## 5. Android 中加载核心类

模型文件应放在应用私有 `filesDir`，不要放共享外部存储。若模型随 APK 发布，先把 asset 复制到私有目录，再从私有文件加载：

```kotlin
fun copyBundledModel(context: Context): File {
    val directory = File(context.filesDir, "intent-models")
    check(directory.isDirectory || directory.mkdirs()) { "cannot create model directory" }
    val target = File(directory, "intent-model-tutorial-v1.json")
    if (target.exists()) return target

    val temporary = File(directory, ".${target.name}.tmp")
    temporary.delete()
    context.assets.open("intent-model.json").use { input ->
        FileOutputStream(temporary).use { output ->
            input.copyTo(output)
            output.fd.sync()
        }
    }
    if (!temporary.renameTo(target)) {
        temporary.delete()
        error("cannot publish bundled intent model")
    }
    return target
}

val modelFile = copyBundledModel(context)
val model = IntentModelLoader.load(modelFile.toPath())
val classifier = MobileIntentClassifier(model)
```

`IntentModelLoader.load(Path)` 和它使用的 `java.nio.file` API 在 Android 上从 API 26 可用，参见 [Android `Path` API](https://developer.android.com/reference/java/nio/file/Path)。如果最低版本低于 26，应给 loader 增加 `InputStream` 入口，并用 `assets.open(...)` 或 `FileInputStream` 适配；不要假装 `Path` 在所有 Android 版本都可用。

真实 App 还要让 Android 工具链支持这些 Java 17 示例使用的 record，或把 record 机械改写为不可变普通类。无论采用哪种语法，都不能删掉构造校验和防御性复制。

## 6. 在后台线程预测

模型加载和预测都不要阻塞主线程。最小做法是让一个串行执行器拥有分类器：

```kotlin
class IntentPredictor(
    private val classifier: MobileIntentClassifier,
) : Closeable {
    private val executor = Executors.newSingleThreadExecutor()

    fun predict(text: String): Future<MobileIntentClassifier.Prediction> =
        executor.submit<MobileIntentClassifier.Prediction> {
            classifier.predict(text)
        }

    override fun close() {
        executor.shutdownNow()
    }
}
```

调用方不能在主线程上执行 `future.get()`；应在自己的协程、任务层或生命周期组件里等待并把结果映射成 UI 状态。用户取消页面或会话时，也要取消尚未消费的任务。

输入文本可能包含订单、账号或聊天隐私。默认不要记录原文、完整候选或 text-file 内容；需要排错时记录脱敏后的请求 ID、模型版本、耗时、intent 和 reason 即可。

## 7. 随 APK 复制还是运行时下载

| 方案 | 适合场景 | 代价 |
| --- | --- | --- |
| copy-to-assets | 制品小、必须首次离线可用、更新频率低 | 每次换模型都要发 App 版本 |
| runtime download | 模型要独立灰度、快速回滚或按租户分发 | 要补下载校验、版本切换和失败恢复 |

这个 JSON 制品通常很小，第一版优先随 APK 分发更容易验证。需要独立更新时再使用运行时下载，但下载完成不等于可以加载。

正式下载流程至少做到：

1. 下载到目标私有目录内的 staged 临时文件，保证它与版本文件位于同一文件系统。
2. 期望 SHA-256 来自 HTTPS 下的可信或签名发布清单；只从同一下载响应读取哈希不能证明真实性。
3. 对 staged 文件校验大小和 SHA-256，再调用 `IntentModelLoader.load` 验证 schema、algorithm、normalization 和统计量。
4. 用 hard link 原子 no-clobber 发布 content-addressed 不可变版本文件；同名目标已存在时必须失败，不能覆盖。
5. staged 删除后，不可变版本 hard link 仍指向同一份已经验证的文件内容。
6. 用同目录临时文件写入版本文件名，刷新到磁盘后原子替换小型 `current` 指针。
7. 保留切换前的版本名和上一版文件；新版本启动或 smoke test 失败时原子切回上一版。
8. schema、algorithm 或 normalization 不兼容时拒绝更新，继续使用旧版本。

## 8. 下载校验与原子切换核心代码

下面 Java 片段省略网络框架，只接收已经建立的下载流。staged 文件、不可变版本文件和 `current` 指针都在同一个应用私有目录；版本文件名同时包含发布版本和完整 SHA-256：

```java
record InstallResult(Path activeVersion, String previousVersionFile) {}

static InstallResult installVersion(
        Path directory,
        String version,
        String expectedSha256,
        InputStream body
) throws Exception {
    if (version == null || expectedSha256 == null
            || version.length() > 64
            || !version.matches("[A-Za-z0-9._-]+")
            || !expectedSha256.matches("[0-9a-f]{64}")) {
        throw new IllegalArgumentException("invalid model version or SHA-256");
    }
    Files.createDirectories(directory);
    String artifactName = "intent-model-" + version + "-" + expectedSha256 + ".json";
    Path versionFile = directory.resolve(artifactName);
    Path staged = Files.createTempFile(directory, ".download-", ".staged");
    try {
        try (InputStream input = body;
             FileOutputStream output = new FileOutputStream(staged.toFile())) {
            byte[] buffer = new byte[8192];
            long total = 0;
            for (int count; (count = input.read(buffer)) != -1;) {
                total += count;
                if (total > IntentModelLoader.MAX_ARTIFACT_BYTES) {
                    throw new IllegalArgumentException("intent model is too large");
                }
                output.write(buffer, 0, count);
            }
            output.flush();
            output.getFD().sync();
        }

        if (!sha256(staged).equals(expectedSha256)) {
            throw new SecurityException("intent model SHA-256 mismatch");
        }
        IntentModelLoader.load(staged); // 所有兼容性检查都发生在发布前

        // 参数顺序是 link, existing。创建操作对同名目标是真正的 no-clobber；
        // 目标已存在时抛 FileAlreadyExistsException，不会覆盖不可变版本。
        Files.createLink(versionFile, staged);
        Files.delete(staged); // versionFile 仍保留同一已验证 inode

        Path currentPointer = directory.resolve("current");
        String previousVersionFile = readCurrentPointer(currentPointer);
        replaceCurrentPointer(directory, artifactName);
        return new InstallResult(versionFile, previousVersionFile);
    } finally {
        Files.deleteIfExists(staged);
    }
}

static String readCurrentPointer(Path currentPointer) throws IOException {
    try {
        String value = new String(
                Files.readAllBytes(currentPointer),
                StandardCharsets.UTF_8
        ).trim();
        if (value.isEmpty() || value.contains("/") || value.contains("\\")) {
            throw new IOException("invalid current model pointer");
        }
        return value;
    } catch (NoSuchFileException missing) {
        return null;
    }
}

static void replaceCurrentPointer(Path directory, String artifactName)
        throws IOException {
    if (artifactName == null || artifactName.isBlank()
            || artifactName.contains("/") || artifactName.contains("\\")) {
        throw new IllegalArgumentException("invalid model pointer target");
    }
    Path pointerTemp = Files.createTempFile(directory, ".current-", ".tmp");
    try {
        try (FileOutputStream output = new FileOutputStream(pointerTemp.toFile())) {
            output.write(artifactName.getBytes(StandardCharsets.UTF_8));
            output.flush();
            output.getFD().sync();
        }
        try {
            Files.move(
                    pointerTemp,
                    directory.resolve("current"),
                    StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING
            );
        } catch (AtomicMoveNotSupportedException unsupported) {
            throw new IOException("atomic current-pointer switch is unavailable", unsupported);
        }
    } finally {
        Files.deleteIfExists(pointerTemp);
    }
}

static String sha256(Path path) throws Exception {
    MessageDigest digest = MessageDigest.getInstance("SHA-256");
    try (InputStream input = Files.newInputStream(path)) {
        byte[] buffer = new byte[8192];
        for (int count; (count = input.read(buffer)) != -1;) {
            digest.update(buffer, 0, count);
        }
    }
    StringBuilder hex = new StringBuilder(64);
    for (byte value : digest.digest()) {
        hex.append(String.format(Locale.ROOT, "%02x", value & 0xff));
    }
    return hex.toString();
}
```

这里有两个不同的原子边界：

1. `Files.createLink(versionFile, staged)` 发布不可变内容。它要求 Android API 26、staged 与 versionFile 位于同一文件系统，并要求应用私有文件系统支持 hard link。目标存在、API 或文件系统不支持时都安全失败，旧模型和旧指针不变；不要退化成可能覆盖目标的 `Files.move`。
2. `current` 只是保存版本文件名的小型指针。只有它允许 `ATOMIC_MOVE + REPLACE_EXISTING`；若抛出 `AtomicMoveNotSupportedException`，更新失败且不做非原子 fallback。

进程崩溃发生在下载或校验阶段，只会留下 staged 文件；发生在 `createLink` 之后、删除 staged 或切换指针之前，可能同时留下 staged 名和一个已验证但未激活的不可变 hard link，旧 `current` 仍有效；发生在 pointer temp 写入阶段，只会多一个临时指针；发生在原子指针切换之后，读取者只会看到完整的新指针。启动清理可以删除过期 staged、pointer temp 和未被 current/previous 引用的版本，但不能提前删除上一版。

`InstallResult.previousVersionFile` 记录切换前的版本名。回滚时先重新加载该不可变文件确认仍兼容，再调用 `replaceCurrentPointer(directory, previousVersionFile)` 原子切回。并发发布同一个 artifact 时，只有一个 `createLink` 成功，其他安装者得到 `FileAlreadyExistsException`；不同版本之间仍应由上层串行化更新或比较发布代次，避免旧任务最后写入 `current`。

## 9. 兼容性与资源边界

Java 加载器对输入有明确上限：

| 边界 | 当前值 | 目的 |
| --- | --- | --- |
| artifact 文件 | 16 MiB | 防止异常模型耗尽内存 |
| JSON nesting | 64 层 | 防止恶意深层 JSON 递归 |
| `--text-file` | 1 MiB | 限制命令行测试输入 |

模型和 text-file 都使用 strict UTF-8。规范化 version 1 固定 Python 3.13 / Unicode 15.1 的整体小写、字母数字过滤与字符 unigram/bigram 行为，Java 使用生成后的固定表，不跟随设备 JDK Unicode 版本漂移。

加载器会拒绝未知顶层字段、schema 不为 1、algorithm 不为 `multinomial_naive_bayes`、normalization 不兼容、阈值越界、负计数、标签不一致、总数不一致和词表不一致。拒绝新模型时不要清空当前分类器，应继续服务上一版并记录不含用户输入的错误摘要。

## 10. 什么时候升级到 ONNX Runtime Mobile

当前分类器适合标签少、边界稳定、模型要极小且必须离线解释的任务。出现下面信号时，再评估 [ONNX Runtime Mobile](https://onnxruntime.ai/docs/tutorials/mobile/)：

1. 字符 n-gram 在同义表达、多语言或长文本上的准确率达到瓶颈。
2. 已有经过独立 test 验证的轻量神经分类器和 ONNX 导出链路。
3. 需要可复用的算子优化、量化或硬件加速，而不是手写模型数学。
4. 目标真机上的包体、内存、首推理延迟和耗电仍满足预算。

不要只因为 ONNX 更“像机器学习”就替换这个 JSON 模型。升级后仍要保留同一标签体系、train/validation/test 纪律、`unknown` 策略、artifact 版本、SHA-256、回滚和跨端评估。

## 本章小结

端侧部署的关键不是把 JSON 放进 assets，而是建立可验证的边界：Python 只训练一次，Java/Android 只加载制品；同一 artifact 和 parity cases 保证跨端一致；私有存储、哈希、兼容性校验、后台执行、原子切换和上一版回滚保证更新失败时仍然可控。
