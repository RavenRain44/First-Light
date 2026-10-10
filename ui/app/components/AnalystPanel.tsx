import { useState } from 'react'
import { Bot, CornerDownLeft, Wrench } from 'lucide-react'
import { post } from '../api'

interface Message { role: 'user' | 'analyst'; text: string; citations?: string[]; toolCalls?: Array<{ tool: string; arguments: Record<string, unknown> }> }

export default function AnalystPanel({ facilityId }: { facilityId: string }) {
  const [question, setQuestion] = useState('Why not closure?')
  const [messages, setMessages] = useState<Message[]>([{ role: 'analyst', text: 'Ask why the posture was selected, what would change it, or who is affected. I can read evidence and call deterministic tools; I cannot write a decision record.' }])
  const [busy, setBusy] = useState(false)
  async function ask(value = question) {
    if (!value.trim() || busy) return
    setMessages((items) => [...items, { role: 'user', text: value }])
    setQuestion('')
    setBusy(true)
    try {
      const response = await post<{ answer: string; citations: string[]; tool_calls: Array<{ tool: string; arguments: Record<string, unknown> }> }>('/analyst/chat', { facility_id: facilityId, question: value })
      setMessages((items) => [...items, { role: 'analyst', text: response.answer, citations: response.citations, toolCalls: response.tool_calls }])
    } catch (error) {
      setMessages((items) => [...items, { role: 'analyst', text: `Analyst unavailable: ${(error as Error).message}` }])
    } finally { setBusy(false) }
  }
  return (
    <section className="page analyst-page">
      <div className="page-heading"><p className="eyebrow">Read-only tool-calling agent</p><h1>Ask the analyst</h1><p>Tool calls stay visible. The agent has no tool that can approve, send, or alter a decision.</p></div>
      <div className="quick-prompts">{['Why not closure?', 'What if onset is 2 hours earlier?', "Who's affected?"].map((item) => <button key={item} onClick={() => { setQuestion(item); void ask(item) }}>{item}</button>)}</div>
      <div className="analyst-console"><div className="chat-log">{messages.map((message, index) => <div className={`chat-message ${message.role}`} key={index}>{message.role === 'analyst' && <Bot size={20} />}<div><span>{message.role === 'analyst' ? 'FirstLight analyst' : 'You'}</span><p>{message.text}</p>{message.toolCalls?.map((call, toolIndex) => <details className="tool-call" key={toolIndex} open><summary><Wrench size={14} />Called <code>{call.tool}</code></summary><pre>{JSON.stringify(call.arguments, null, 2)}</pre></details>)}{message.citations && <div className="citations">Evidence: {message.citations.join(' · ')}</div>}</div></div>)}{busy && <div className="typing">Analyst is checking deterministic tools…</div>}</div><form onSubmit={(event) => { event.preventDefault(); void ask() }}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about this recommendation…" /><button aria-label="Send" disabled={busy}><CornerDownLeft size={18} /></button></form></div>
    </section>
  )
}
