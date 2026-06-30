import '../env.js'

import { createStepFunProviderFromEnv } from './stepfun.provider.js'
import type { AgentMessage } from '../core/ports/llm.port.js'

async function main() {
  console.log('=== MozilCode StepFun Provider 测试 ===\n')

  const provider = createStepFunProviderFromEnv()

  console.log('模型:', provider.modelName)
  console.log('已配置:', provider.isConfigured())

  if (!provider.isConfigured()) {
    console.error('❌ 缺少环境变量，请检查 .env 文件')
    process.exit(1)
  }

  const messages: AgentMessage[] = [
    {
      id: 'msg-1',
      role: 'user',
      content: '你好，用一句话介绍你自己',
      timestamp: Date.now(),
    },
  ]

  console.log('\n--- 流式输出 ---')
  let fullText = ''
  try {
    for await (const chunk of provider.generateStream({ messages })) {
      if (chunk.delta) {
        process.stdout.write(chunk.delta)
        fullText += chunk.delta
      }
      if (chunk.toolCall) {
        console.log('\n[tool_call]', chunk.toolCall.function.name, chunk.toolCall.function.arguments)
      }
      if (chunk.finishReason) {
        console.log('\n[finish]', chunk.finishReason)
      }
    }
    console.log('\n\n✅ 流式测试成功')
  } catch (err) {
    console.error('\n❌ 流式测试失败:', err)
    process.exit(1)
  }
}

main()
