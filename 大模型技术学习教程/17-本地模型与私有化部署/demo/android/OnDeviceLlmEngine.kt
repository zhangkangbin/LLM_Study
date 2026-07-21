/*
 * Android 端 GGUF 推理核心集成片段，不是本仓库可独立编译的 Android 工程。
 * 使用前需要 Android SDK、kotlinx-coroutines，并从下面固定版本的 llama.cpp
 * checkout 导入 examples/llama.android/lib 模块：
 *
 * llama.cpp commit: 505b1ed15ca80e2a19f12ff4ac365e40fb374053
 * AiChat.kt:
 * https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/lib/src/main/java/com/arm/aichat/AiChat.kt
 * InferenceEngine.kt:
 * https://github.com/ggml-org/llama.cpp/blob/505b1ed15ca80e2a19f12ff4ac365e40fb374053/examples/llama.android/lib/src/main/java/com/arm/aichat/InferenceEngine.kt
 *
 * 该版本的 InferenceEngine 默认 predictLength 是 1024；本封装把业务默认值收紧为 256。
 */

import android.content.Context
import com.arm.aichat.AiChat
import com.arm.aichat.InferenceEngine
import java.io.Closeable
import java.io.File
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * 对 llama.cpp Android [InferenceEngine] 的最小生命周期封装。
 *
 * [AiChat.getInferenceEngine] 返回进程内单例，因此应用应只创建一个应用级的本封装实例。
 * 同一实例的 load、generate 和 unload 会串行执行；任一时刻最多收集一个 generation。
 * 取消 [generate] 返回的 Flow 会把取消传播给上游 collection，但这不承诺 native 推理会
 * 立即停止；调用方必须等待 collecting Job 真正结束后，才能 unload 或 close。
 *
 * Activity/Fragment 应在 onStop 取消 collecting Job 并等待或确认它已经结束，再在最终的
 * onDestroy 阶段调用 [close]。不要在 UI 线程用 runBlocking 等待。配置变更时不要销毁这个
 * 进程级单例；把封装放在合适的应用级 owner 中，并只在 owner 永久结束时 close。
 * [close] 成功后再次调用没有效果，其他公开操作都会被拒绝。
 *
 * 上游的 cleanUp 在 ModelReady 状态卸载模型，在 Error 状态复位；其他上游状态会抛出
 * IllegalStateException。本封装的 [unload] 是 suspend 方法，把该同步清理移到 IO dispatcher。
 */
class OnDeviceLlmEngine(
    context: Context,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
    private val inferenceDispatcher: CoroutineDispatcher = Dispatchers.Default,
) : Closeable {
    private val engine: InferenceEngine =
        AiChat.getInferenceEngine(context.applicationContext)

    // 串行化本实例的模型装载、生成和卸载，避免改变 native 状态时仍有活跃生成。
    private val generationMutex = Mutex()
    private val lifecycleLock = Any()
    private var activeNativeOperations = 0
    private var closed = false

    /** 装载一个可读的 GGUF 文件，并可选地在装载后立即设置系统提示词。 */
    suspend fun load(modelFile: File, systemPrompt: String? = null) =
        withContext(ioDispatcher) {
            ensureOpen()
            require(modelFile.isFile) { "model file is missing or not a regular file" }
            generationMutex.withLock {
                withNativeOperation {
                    engine.loadModel(modelFile.absolutePath)
                    if (!systemPrompt.isNullOrBlank()) {
                        engine.setSystemPrompt(systemPrompt)
                    }
                }
            }
        }

    /**
     * 生成 token 文本流。参数校验在调用时完成，native 状态校验在开始收集时完成。
     * 异常消息不会包含 prompt 内容。
     */
    fun generate(prompt: String, maxOutputTokens: Int = 256): Flow<String> {
        require(prompt.isNotBlank()) { "prompt is blank" }
        require(maxOutputTokens in 1..1024) {
            "maxOutputTokens must be between 1 and 1024"
        }
        ensureOpen()

        return flow {
            generationMutex.withLock {
                withNativeOperation {
                    engine.sendUserPrompt(prompt, maxOutputTokens).collect { token ->
                        emit(token)
                    }
                }
            }
        }.flowOn(inferenceDispatcher)
    }

    /**
     * 卸载当前模型（或按上游语义复位 Error 状态）。
     * 调用前必须取消并等待 generation collection 结束；否则本调用会等到其结束。
     */
    suspend fun unload() = withContext(ioDispatcher) {
        generationMutex.withLock {
            withNativeOperation {
                engine.cleanUp()
            }
        }
    }

    /**
     * 永久销毁上游进程级单例。
     *
     * close 不会在 UI 线程阻塞等待活跃 coroutine；若仍有 native 操作，它会明确失败。
     * 先取消并等待 collecting Job，然后从非 UI 线程在生命周期 owner 最终销毁时调用。
     */
    override fun close() {
        synchronized(lifecycleLock) {
            if (closed) return
            check(activeNativeOperations == 0) {
                "cancel and await active model operations before closing the engine"
            }
            // 先封闭入口，避免 destroy 与新开始的 load/generate/unload 竞争。
            closed = true
        }
        engine.destroy()
    }

    private fun ensureOpen() {
        synchronized(lifecycleLock) {
            check(!closed) { "engine is closed" }
        }
    }

    private suspend fun <T> withNativeOperation(block: suspend () -> T): T {
        synchronized(lifecycleLock) {
            check(!closed) { "engine is closed" }
            activeNativeOperations += 1
        }
        try {
            return block()
        } finally {
            synchronized(lifecycleLock) {
                activeNativeOperations -= 1
            }
        }
    }
}
