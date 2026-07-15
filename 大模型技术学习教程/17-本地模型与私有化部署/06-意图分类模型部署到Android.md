# 意图分类模型部署到 Android

阶段 16 已经完成意图分类的训练、validation 校准和 JSON 制品导出。本章只处理部署边界：用 Python 生成一次制品，再让纯 Java 和 Android 加载同一份制品做离线推理。

先阅读 [意图识别与分类训练实战](../16-微调与模型定制/05-意图识别与分类训练实战.md)。本章不创建完整 Android Studio 工程，不展开 UI、Gradle、Manifest 或网络框架，只保留可编译命令和核心集成代码。

## 1. 核心文件与边界

Java 示例包含四个 package-free 文件：

- [MiniJson.java](./demo/android/MiniJson.java)：解析固定 JSON schema。
- [IntentModelLoader.java](./demo/android/IntentModelLoader.java)：读取、校验并构造不可变模型。
- [MobileIntentClassifier.java](./demo/android/MobileIntentClassifier.java)：规范化、n-gram、概率和拒识推理。
- [MobileIntentClassifierTest.java](./demo/android/MobileIntentClassifierTest.java)：加载、损坏制品、资源边界和推理测试。

这些源码不依赖 Android Framework，也不需要第三方机器学习 Runtime，因此可以先用桌面 JDK 17 命令行验证。这里的“纯 Java”只描述依赖边界：桌面 `javac/java` 成功不等于已经通过 AGP/D8、ART 和目标设备文件系统验证。四个文件保持 package-free 是为了让教程命令直接运行；复制到真实 App 时，可以给它们统一添加应用包名，并按第 5 节处理 Android API 差异。

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

模型文件应放在应用私有 `filesDir`，不要放共享外部存储。若模型随 APK 发布，首次安装也必须走第 8 节的同一套 content-addressed 安装器，不能使用固定 `.tmp`、`exists()` 后直接返回或 `renameTo` 覆盖目标。下面只是 Android 调用适配器，不是另一套发布实现：

```kotlin
fun installBundledModel(context: Context): Path {
    val directory = File(context.filesDir, "intent-models")
    // 该常量由可信构建流程从最终打包的 intent-model.json 字节生成，不能由 asset 自报。
    val expectedArtifactSha256 = BuildConfig.INTENT_MODEL_ARTIFACT_SHA256
    context.assets.open("intent-model.json").use { input ->
        return ModelInstaller.installFromStream(
            directory.toPath(),
            expectedArtifactSha256,
            input,
        ).activeVersion
    }
}

val modelFile = installBundledModel(context)
val model = IntentModelLoader.load(modelFile)
val classifier = MobileIntentClassifier(model)
```

asset 与网络更新必须由同一个串行安装 worker 调用 `installFromStream`。安装器会创建同目录唯一 staged 文件，复制完成并关闭写句柄、执行 `FileDescriptor.sync()`，再校验可信 artifact SHA 和 loader schema；content-addressed 目标已存在时也会重新校验，而不是因 `exists()` 就信任它。APK 内置模型的 SHA 常量应由可信构建步骤根据最终打包 artifact 生成并纳入受签名 APK，不能在运行时从同一 asset 重新计算后当成“期望值”。

当前四个 Java 源文件**原样**接入 Android 时，保守边界是 API 34，并且仍要用实际 AGP/D8/ART 与目标真机验证；原因不是推理算法，而是源码使用了多个不同 API 断点：

| 源码/API | Android 官方起始 API | 结论 |
| --- | ---: | --- |
| `java.nio.file.Path`、`Files.createLink`/`isSymbolicLink` | 26 | 第 8 节 NIO/hard-link 协议的起点，不代表整套源码 minSdk 是 26 |
| `InputStream.readNBytes`、`String.isBlank` | 33 | API 26–32 原样不可用 |
| `Path.of`、`java.lang.Record` | 34 | 当前 CLI/record 源码原样运行的保守下限 |

参见 Android 官方的 [`InputStream`](https://developer.android.com/reference/java/io/InputStream)、[`String`](https://developer.android.com/reference/java/lang/String)、[`Path`](https://developer.android.com/reference/java/nio/file/Path)、[`Record`](https://developer.android.com/reference/java/lang/Record) 和 [`Files`](https://developer.android.com/reference/java/nio/file/Files) API 页面。

若 App 支持 API 26–33，需要做完并真机验证这些适配：

1. 把 `readNBytes(limit + 1)` 改为有上限的手工读取循环，仍须在超限时失败。
2. 把 `String.isBlank()` 改为语义等价的本地 helper，不能简单删掉空白校验。
3. CLI `main`、测试和其中的 `Path.of` 不进入 App；App 代码使用 API 26 的 [`File.toPath()`](https://developer.android.com/reference/java/io/File) 或 [`Paths.get()`](https://developer.android.com/reference/java/nio/file/Paths)。
4. 把 record 机械改写为带构造校验、防御性复制、只读访问器的普通不可变类；只有在目标 AGP/D8/ART/设备组合确实验证过 record desugaring 时，才能保留 record。

若最低版本低于 26，还要给 loader 增加有同样大小上限和 strict UTF-8 的 `InputStream` 入口，并另行设计不依赖 hard link/NIO 原子移动的发布协议；本章第 8 节不能直接宣称兼容。

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

这个 JSON 制品通常很小，第一版优先随 APK 分发更容易验证。需要独立更新时再使用运行时下载，但 asset 首次复制和网络更新应复用同一个安装器；输入来源不同，安全状态机不能分叉。

先区分两个容易混淆的 SHA：

| 字段/值 | 哈希对象 | 用途 |
| --- | --- | --- |
| 发布清单或 `BuildConfig.INTENT_MODEL_ARTIFACT_SHA256` | **最终 JSON artifact 的完整字节** | 文件名、下载/asset 完整性校验、激活前复验 |
| `training_metadata.dataset_sha256` | 训练流水线定义的规范化数据集 | 训练追踪与复现，不是 artifact 文件哈希，不能用于安装校验 |

SHA-256 只能说明“收到的字节与期望字节相同”，不能证明发布者身份。运行时的 `expectedSha256` 必须来自经过认证或签名验证的发布清单；清单还要包含单调递增的发布代次/防回滚状态，并持久化已接受的最高代次。把哈希与模型放在同一个未签名响应中，或只依赖 HTTPS 下载成功，都不能替代发布认证与 anti-rollback。asset 的期望哈希则来自可信构建并随签名 APK 固化。

正式安装流程至少做到：

1. 单一更新 worker 串行处理 asset 与网络输入；多进程 App 还要让专用更新进程或 OS `FileLock` 覆盖完整协议。
2. 在目标私有目录创建唯一、同目录 staged 文件；有界复制后先关闭写句柄并 `FileDescriptor.sync()`。
3. 对 staged 文件校验 artifact 字节 SHA-256，再调用 `IntentModelLoader.load` 验证 schema、algorithm、normalization 和统计量。
4. 用 `Files.createLink(versionFile, staged)` 建立纯 content-addressed 名称 `intent-model-<64位小写hex>.json`。它只提供目录项创建的 no-clobber，不会把 inode 变成只读。
5. 无论 link 是新建还是目标原本已存在，都从 **version 路径**重新校验文件大小、SHA-256 与 loader schema；成功后才能删除 staged、写指针。
6. 使用同目录唯一临时文件原子替换小型 `previous` 和 `current` 指针。读取者每次严格解析并复验目标；`current` 失败则严格尝试 `previous`，两者都失败时禁用分类功能或使用受信的 bundled fallback。
7. schema、algorithm、normalization、哈希或指针不兼容时拒绝更新，继续使用已验证的上一版。

## 8. 下载校验与原子切换核心代码

下面 Java 片段展示协议核心，省略网络/清单验签、跨进程锁、清理、日志和平台级强持久化，因此不是可直接粘贴进生产的完整类。为便于单独编译检查，列出片段实际需要的 imports。staged、version 和 pointer 都必须位于同一个应用私有目录：

```java
import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.concurrent.locks.ReentrantLock;

final class ModelInstaller {
    private static final long MAX_ARTIFACT_BYTES = 16L * 1024 * 1024;
    private static final int MAX_POINTER_BYTES = 96;
    private static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");
    private static final Pattern ARTIFACT_NAME = Pattern.compile(
            "intent-model-([0-9a-f]{64})\\.json"
    );
    // 只串行化当前进程；多进程 App 必须另加覆盖完整协议的 OS 锁或专用更新进程。
    private static final ReentrantLock INSTALL_LOCK = new ReentrantLock();

    private ModelInstaller() {}

    static final class InstallResult {
        private final Path activeVersion;
        private final String previousVersionFile;

        InstallResult(Path activeVersion, String previousVersionFile) {
            this.activeVersion = activeVersion;
            this.previousVersionFile = previousVersionFile;
        }

        public Path getActiveVersion() {
            return activeVersion;
        }

        public String getPreviousVersionFile() {
            return previousVersionFile;
        }
    }

    static InstallResult installFromStream(
            Path directory,
            String expectedSha256,
            InputStream body
    ) throws Exception {
        // 先验证哈希，再让它参与文件名构造。
        if (expectedSha256 == null || !SHA256.matcher(expectedSha256).matches()) {
            throw new IllegalArgumentException("invalid expected artifact SHA-256");
        }
        if (directory == null || body == null) {
            throw new IllegalArgumentException("directory/body must not be null");
        }

        INSTALL_LOCK.lock();
        Path staged = null;
        try {
            Files.createDirectories(directory);
            Path base = directory.toAbsolutePath().normalize();
            if (Files.isSymbolicLink(base)) {
                throw new IOException("model directory must not be a symbolic link");
            }
            staged = Files.createTempFile(base, ".download-", ".staged");

            // 复制结束时关闭 staged 的写句柄，然后才开始校验/发布。
            try (InputStream input = body;
                 FileOutputStream output = new FileOutputStream(staged.toFile())) {
                byte[] buffer = new byte[8192];
                long total = 0;
                for (int count; (count = input.read(buffer)) != -1;) {
                    if (count > MAX_ARTIFACT_BYTES - total) {
                        throw new IllegalArgumentException("intent model is too large");
                    }
                    output.write(buffer, 0, count);
                    total += count;
                }
                output.flush();
                output.getFD().sync();
            }

            verifyStaged(staged, expectedSha256);
            String artifactName = "intent-model-" + expectedSha256 + ".json";
            Path versionFile = resolveDirectVersion(base, artifactName);
            boolean created = false;
            try {
                // 参数顺序是 link, existing；同名目标存在时不覆盖。
                Files.createLink(versionFile, staged);
                created = true;
            } catch (FileAlreadyExistsException existing) {
                // 可复用，但下面仍从 version 路径重验字节和 schema。
            }

            try {
                validateVersionFile(base, artifactName, expectedSha256);
            } catch (Exception invalidPublishedVersion) {
                if (created) {
                    Files.deleteIfExists(versionFile);
                }
                throw invalidPublishedVersion;
            }

            Files.delete(staged);
            staged = null;

            String oldActive = firstValidPointerName(base);
            if (oldActive != null && !oldActive.equals(artifactName)) {
                replacePointer(base, "previous", oldActive);
            }
            replacePointer(base, "current", artifactName);
            return new InstallResult(versionFile, oldActive);
        } finally {
            try {
                if (staged != null) {
                    Files.deleteIfExists(staged);
                }
            } finally {
                INSTALL_LOCK.unlock();
            }
        }
    }

    private static void verifyStaged(Path staged, String expectedSha256)
            throws Exception {
        if (Files.size(staged) > MAX_ARTIFACT_BYTES
                || !sha256(staged).equals(expectedSha256)) {
            throw new SecurityException("intent model artifact SHA-256 mismatch");
        }
        IntentModelLoader.load(staged);
    }

    static Path loadCurrentOrPrevious(Path directory) throws IOException {
        IOException currentFailure;
        try {
            return validatePointer(directory, "current");
        } catch (Exception error) {
            currentFailure = asIOException("current pointer is unusable", error);
        }
        try {
            return validatePointer(directory, "previous");
        } catch (Exception error) {
            IOException bothFailed = asIOException(
                    "current and previous pointers are unusable",
                    error
            );
            bothFailed.addSuppressed(currentFailure);
            throw bothFailed;
        }
    }

    private static Path validatePointer(Path directory, String pointerName)
            throws Exception {
        String artifactName = readPointerNameStrict(directory, pointerName);
        if (artifactName == null) {
            throw new NoSuchFileException(pointerName);
        }
        return validateVersionFile(directory, artifactName, null);
    }

    static String readPointerNameStrict(Path directory, String pointerName)
            throws IOException {
        requirePointerName(pointerName);
        Path base = directory.toAbsolutePath().normalize();
        Path pointer = base.resolve(pointerName);
        if (Files.isSymbolicLink(pointer)) {
            throw new IOException(pointerName + " pointer must not be a symbolic link");
        }
        byte[] encoded;
        try {
            encoded = readBounded(pointer, MAX_POINTER_BYTES);
        } catch (NoSuchFileException missing) {
            return null;
        }

        final String value;
        try {
            value = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(encoded))
                    .toString();
        } catch (CharacterCodingException invalidUtf8) {
            throw new IOException(pointerName + " pointer is not strict UTF-8", invalidUtf8);
        }
        if (!ARTIFACT_NAME.matcher(value).matches()) {
            throw new IOException(pointerName + " pointer has invalid content");
        }
        resolveDirectVersion(base, value); // 同时执行 direct-child 与 symlink 检查。
        return value; // 不 trim；换行、空格、大小写变化都会被拒绝。
    }

    static Path validateVersionFile(
            Path directory,
            String artifactName,
            String expectedSha256
    ) throws Exception {
        Matcher matcher = ARTIFACT_NAME.matcher(artifactName == null ? "" : artifactName);
        if (!matcher.matches()) {
            throw new IOException("invalid content-addressed artifact name");
        }
        String embeddedSha256 = matcher.group(1);
        if (expectedSha256 != null && !embeddedSha256.equals(expectedSha256)) {
            throw new SecurityException("artifact name SHA-256 mismatch");
        }
        Path versionFile = resolveDirectVersion(directory, artifactName);
        if (!Files.isRegularFile(versionFile, LinkOption.NOFOLLOW_LINKS)
                || Files.size(versionFile) > MAX_ARTIFACT_BYTES
                || !sha256(versionFile).equals(embeddedSha256)) {
            throw new SecurityException("version artifact bytes are invalid");
        }
        IntentModelLoader.load(versionFile); // 每次激活/读取都复验 schema。
        return versionFile;
    }

    static Path resolveDirectVersion(Path directory, String artifactName)
            throws IOException {
        if (artifactName == null || !ARTIFACT_NAME.matcher(artifactName).matches()) {
            throw new IOException("invalid content-addressed artifact name");
        }
        Path base = directory.toAbsolutePath().normalize();
        Path candidate = base.resolve(artifactName).normalize();
        if (!base.equals(candidate.getParent())) {
            throw new IOException("artifact must be a direct child of model directory");
        }
        if (Files.isSymbolicLink(candidate)) {
            throw new IOException("artifact target must not be a symbolic link");
        }
        return candidate;
    }

    static void replacePointer(Path directory, String pointerName, String artifactName)
            throws Exception {
        requirePointerName(pointerName);
        Path base = directory.toAbsolutePath().normalize();
        validateVersionFile(base, artifactName, null); // rollback 也走同样严格校验。
        Path pointer = base.resolve(pointerName);
        if (Files.isSymbolicLink(pointer)) {
            throw new IOException(pointerName + " pointer must not be a symbolic link");
        }

        Path pointerTemp = Files.createTempFile(base, "." + pointerName + "-", ".tmp");
        try {
            try (FileOutputStream output = new FileOutputStream(pointerTemp.toFile())) {
                output.write(artifactName.getBytes(StandardCharsets.UTF_8));
                output.flush();
                output.getFD().sync();
            }
            try {
                Files.move(
                        pointerTemp,
                        pointer,
                        StandardCopyOption.ATOMIC_MOVE,
                        StandardCopyOption.REPLACE_EXISTING
                );
            } catch (AtomicMoveNotSupportedException unsupported) {
                throw new IOException("atomic pointer switch is unavailable", unsupported);
            }
        } finally {
            Files.deleteIfExists(pointerTemp);
        }
    }

    private static String firstValidPointerName(Path directory) {
        for (String pointerName : new String[] {"current", "previous"}) {
            try {
                String artifactName = readPointerNameStrict(directory, pointerName);
                if (artifactName != null) {
                    validateVersionFile(directory, artifactName, null);
                    return artifactName;
                }
            } catch (Exception invalidOrMissing) {
                // 安装可信新版本仍可继续；不会把无效旧目标写入 previous。
            }
        }
        return null;
    }

    private static byte[] readBounded(Path path, int limit) throws IOException {
        try (InputStream input = Files.newInputStream(path);
             ByteArrayOutputStream output = new ByteArrayOutputStream(limit)) {
            byte[] buffer = new byte[128];
            for (int count; (count = input.read(buffer)) != -1;) {
                if (count > limit - output.size()) {
                    throw new IOException("pointer exceeds " + limit + " bytes");
                }
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }

    private static void requirePointerName(String pointerName) {
        if (!"current".equals(pointerName) && !"previous".equals(pointerName)) {
            throw new IllegalArgumentException("pointer must be current or previous");
        }
    }

    private static IOException asIOException(String message, Exception error) {
        return error instanceof IOException
                ? (IOException) error
                : new IOException(message, error);
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
}
```

`Files.createLink(link, existing)` 创建的新目录项与 staged 指向同一个底层文件对象（通常称同一 inode），删除 staged 名不会删除 version 名所引用的内容；目标名已存在时的 no-clobber 也不会覆盖它。但 hard link **不是只读机制**：通过任一链接打开写句柄都能改同一 inode。“不可变版本”只是应用层约定。发布成功后，同一 UID 的正常代码绝不能再以写模式打开 version 文件或仍存活的 staged inode；安装器必须单写者串行执行，并在 link 之后、pointer 之前从 version 路径复验 SHA 与 schema。

威胁边界也要写清楚：协议防止普通崩溃、截断下载、错误哈希、目录名碰撞与无效 schema，不防同 UID 已被攻陷的代码/native library、root、设备文件系统破坏或能写应用私有目录的攻击者。这些主体仍可改写/删除 inode；严格读取复验只能检测并停用，不能恢复发布者真实性。

`current`/`previous` 文件只接受一个无换行的精确名称 `intent-model-<64位小写hex>.json`，最大 96 字节并使用 strict UTF-8；`.`、`..`、`../x`、大写 hex、额外空白、过长内容、非 direct-child 目标和符号链接都会被拒绝。解析时先做完整正则，再 `resolve(...).normalize()` 并要求 parent 等于模型目录。加载 `current` 时还要确认目标存在、不是 symlink、artifact 字节 SHA 与文件名一致且 loader schema 有效；失败才按完全相同规则尝试 `previous`。两者都失败时，调用方应禁用此分类功能或加载经 APK 签名信任链验证的 bundled fallback，不能“尽量猜一个文件”。

回滚不是绕过校验的特殊路径：先严格读取 `previous`，调用 `validateVersionFile`，再由 `replacePointer(directory, "current", previousName)` 原子切回。单进程 `ReentrantLock` 还不够覆盖多进程竞争；多进程必须用一个专用更新进程，或让 OS 文件锁从 staged 创建一直持有到 pointer 切换完成。

这里保证的是 pointer 的**原子可见性与进程崩溃恢复**：崩溃前后，读取者只看到完整旧指针或完整新指针，遗留 staged/temp 可在启动时清理。它不承诺突然掉电后的强持久化。`FileDescriptor.sync()` 刷新文件内容，但 Java 代码没有 fsync 父目录元数据；若产品要求 power-loss durability，需要平台专用的目录 fsync/事务存储能力，或重启后经验证的持久化组件，不能仅凭 `ATOMIC_MOVE` 宣称已落盘。

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
