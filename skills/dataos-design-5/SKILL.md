---
name: dataos-design-5
description: "DataOS Frontend Option 5: Conversational DataOS — chat-first interface where the primary interaction is talking to your data. AI agents as the UI layer, with rich cards for results. Best for non-technical users and quick exploration."
---

# Option 5: Conversational DataOS

A chat-first interface where you talk to your data. No dashboards, no graphs, no code — just conversation. AI agents handle the complexity and present results as rich interactive cards. The most accessible option.

## Design Philosophy
> "The best interface is no interface. Ask a question, get an answer."

## Visual Identity

- **Palette:** Clean white (#ffffff) background, charcoal (#1f2937) text, blue (#2563eb) primary, green (#16a34a) success, warm gray (#9ca3af) for meta text
- **Typography:** Inter for everything. Clear hierarchy through size and weight only. 16px body, large readable text.
- **Layout:** Centered chat column (680px max), full-height, no panels or sidebars
- **Surfaces:** Message bubbles, rich result cards, subtle shadows. Nothing decorative.

## Core Screens

### 1. Chat Interface (Primary)
```
┌─────────────────────────────────────────────────────────┐
│ DataOS                                         [New Chat]│
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │ 👋 Hi! I'm DataOS. I can help you explore your    │ │
│  │ data, run queries, find relationships, and more.   │ │
│  │                                                    │ │
│  │ Try asking:                                        │ │
│  │ • "What datasets do I have?"                       │ │
│  │ • "Show me sales by region for Q4"                 │ │
│  │ • "What's connected to the customers table?"       │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  You: What's in my dataspace?                           │
│                                                          │
│  DataOS: You have 7 datasets across 3 sources:          │
│                                                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │
│  │ 📊 Sales    │ │ 👤 Customers│ │ 📞 Tickets  │       │
│  │ 2,400 rows  │ │ 150 records │ │ 89 entries  │       │
│  │ Q4 2024     │ │ Active      │ │ 12 open     │       │
│  │ [View]      │ │ [View]      │ │ [View]      │       │
│  └─────────────┘ └─────────────┘ └─────────────┘       │
│                                                          │
│  I also found relationships between them. Want me to     │
│  show the connection map?                                │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Ask DataOS...                              [Send] │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2. Rich Result Cards
- **Data card:** inline table with sortable columns, export button
- **Chart card:** auto-generated visualization with type selector
- **Relationship card:** mini-graph showing connections
- **Evidence card:** source document with highlighted relevant text
- **Action card:** proposed actions with approve/reject buttons
- **File card:** file preview with metadata and download

### 3. Quick Actions Bar
- Floating action buttons above input:
  - "📊 Upload data" — opens file picker
  - "🔍 Run query" — switches to SQL input mode
  - "🤖 Ask agent" — delegates to specialized agent
  - "📋 Generate report" — creates shareable document

### 4. Chat History
- Sidebar (collapsible) with chat sessions
- Search across all past conversations
- Pin important conversations
- Export chat as Markdown

### 5. Agent Activity
- Background agent notifications as chat messages
- "🤖 Agent discovered 3 new relationships" → click to see details
- Agent can proactively suggest insights: "I noticed sales spike on Tuesdays..."
- User can approve/reject/modify agent suggestions

## Component Patterns

### Chat Message (User)
```jsx
<div className="flex justify-end mb-4">
  <div className="max-w-[80%] bg-blue-600 text-white rounded-2xl rounded-br-md px-4 py-3">
    <p className="text-sm leading-relaxed">{message}</p>
  </div>
</div>
```

### Chat Message (DataOS)
```jsx
<div className="flex gap-3 mb-4">
  <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
    <Database className="w-4 h-4 text-blue-600" />
  </div>
  <div className="max-w-[85%]">
    <div className="bg-gray-100 rounded-2xl rounded-tl-md px-4 py-3">
      <p className="text-sm text-gray-800 leading-relaxed">{message}</p>
    </div>
    {cards && <div className="mt-3 space-y-3">{cards}</div>}
  </div>
</div>
```

### Data Result Card
```jsx
<div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
  <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100">
    <div className="flex items-center gap-2">
      <TableIcon className="w-4 h-4 text-gray-400" />
      <span className="text-sm font-medium text-gray-700">{title}</span>
    </div>
    <button className="text-xs text-blue-500 hover:text-blue-600">Export CSV</button>
  </div>
  <div className="overflow-x-auto">
    <table className="w-full text-sm">
      {/* table content */}
    </table>
  </div>
</div>
```

### Chart Card
```jsx
<div className="bg-white border border-gray-200 rounded-xl shadow-sm p-4">
  <div className="flex items-center justify-between mb-3">
    <span className="text-sm font-medium text-gray-700">{title}</span>
    <div className="flex gap-1">
      {['bar', 'line', 'pie'].map(type => (
        <button key={type}
          className={`px-2 py-0.5 text-xs rounded ${activeType === type
            ? 'bg-blue-100 text-blue-600' : 'text-gray-400 hover:text-gray-600'}`}>
          {type}
        </button>
      ))}
    </div>
  </div>
  <div className="h-48">
    {/* chart rendering */}
  </div>
</div>
```

### Input Bar
```jsx
<div className="border border-gray-200 rounded-2xl shadow-sm bg-white
  focus-within:border-blue-300 focus-within:ring-2 focus-within:ring-blue-100
  transition-all">
  <textarea
    className="w-full px-4 py-3 text-sm resize-none outline-none rounded-2xl"
    placeholder="Ask DataOS anything..."
    rows={1}
    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) send(); }}
  />
  <div className="flex items-center justify-between px-3 pb-2">
    <div className="flex gap-1">
      <button className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
        <Paperclip className="w-4 h-4" />
      </button>
      <button className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
        <Code className="w-4 h-4" />
      </button>
    </div>
    <button className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-xl
      hover:bg-blue-700 transition-colors disabled:opacity-50">
      Send
    </button>
  </div>
</div>
```

## Interactions
- **Enter** to send, **Shift+Enter** for newline
- **@ mention** to reference specific datasets: "@sales show me revenue"
- **/ commands** for power users: "/sql SELECT..." "/upload" "/share"
- **Double-click** a result card to expand full-screen
- **Long press** on mobile for context menu (copy, share, ask follow-up)
- **Voice input** button (optional, uses Web Speech API)

## Responsive
- Below 768px: full-width chat, bottom input fixed
- Below 480px: simplified cards, swipe left/right for alternatives
- Mobile: native-feel with pull-to-refresh, haptic feedback
- Tablet: split view — chat left, results right

## Motion
- Message appear: fade in + slide up (200ms ease-out)
- Card appear: staggered entrance (50ms delay between cards)
- Typing indicator: three bouncing dots
- Send button: pulse on send, checkmark on delivered
- Card expand: spring (damping 1.0, response 0.3)
