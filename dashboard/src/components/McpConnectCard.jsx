import React, { useEffect, useState, useCallback } from 'react';
import { Plug, Copy, Check } from 'lucide-react';
import { apiFetch } from '../lib/api';
import { getApiUrl } from '../config';

// "Connect an agent": tells a person how to drive Clip Studio from Claude,
// ChatGPT, Cursor or n8n. This fork has no hosted edition, so every snippet is
// this machine's own MCP URL and none needs a key.
//
// The dashboard proxies /api and /videos but not /mcp, and it runs on its own
// port, so the MCP client must be told the API origin. The server reports it
// (/api/config publicApiUrl, from PUBLIC_API_URL); until that arrives, fall
// back to the page's hostname.

function withMcp(url) {
  const base = String(url || '').replace(/\/+$/, '');
  return base ? `${base}/mcp` : '';
}

function buildClients(url) {
  return [
    {
      id: 'claude-code', label: 'Claude Code', kind: 'code', lang: 'bash',
      snippet: `claude mcp add --transport http clipstudio ${url}`,
      note: 'No key needed on a local install.',
    },
    {
      id: 'claude-desktop', label: 'Claude Desktop', kind: 'code', lang: 'json',
      snippet: `{\n  "mcpServers": {\n    "clipstudio": {\n      "command": "npx",\n      "args": ["-y", "mcp-remote", "${url}"]\n    }\n  }\n}`,
      note: 'Settings → Developer → Edit config (claude_desktop_config.json), then restart Claude.',
    },
    {
      id: 'cursor', label: 'Cursor', kind: 'code', lang: 'json',
      snippet: `{\n  "mcpServers": {\n    "clipstudio": {\n      "url": "${url}"\n    }\n  }\n}`,
      note: 'Settings → MCP → Add new global MCP server (.cursor/mcp.json).',
    },
    {
      id: 'n8n', label: 'n8n', kind: 'steps',
      steps: [
        'Add an "MCP Client Tool" node to your AI Agent.',
        `Endpoint: ${url}  ·  Transport: HTTP Streamable.`,
        'Authentication: none.',
      ],
      snippet: url,
    },
    {
      id: 'curl', label: 'curl', kind: 'code', lang: 'bash',
      snippet: `curl -X POST ${url} \\\n  -H "Content-Type: application/json" \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`,
      note: 'Plain JSON-RPC over HTTP: the same endpoint every client above talks to.',
    },
  ];
}

export default function McpConnectCard({ compact = false }) {
  const [origin, setOrigin] = useState('');
  const [active, setActive] = useState('claude-code');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/api/config')
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (cancelled) return;
        const publicUrl = cfg && cfg.publicApiUrl;
        if (publicUrl) return setOrigin(publicUrl);
        // Same-origin /mcp when the backend serves the page, else the API's
        // default host on this machine. VITE_API_URL covers a split deploy.
        const relative = getApiUrl('/mcp');
        if (relative.startsWith('http')) return setOrigin(relative.replace(/\/mcp$/, ''));
        return setOrigin(`${window.location.protocol}//${window.location.hostname}:8000`);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const url = withMcp(origin) || 'http://localhost:8000/mcp';
  const clients = buildClients(url);
  const current = clients.find((c) => c.id === active) || clients[0];

  const copy = useCallback(() => {
    navigator.clipboard?.writeText(current.snippet).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    }).catch(() => {});
  }, [current]);

  return (
    <div className="card p-6" id="connect-agent">
      <h3 className="font-display lowercase text-lg text-ink mb-1 flex items-center gap-2">
        <Plug size={16} className="text-brass" /> Connect an agent
      </h3>
      <p className="text-muted text-sm mb-4">
        Let Claude, ChatGPT, Cursor or n8n clip and publish for you through the built-in MCP
        server: 13 tools (process a video or upload one, check a job, read a transcript, render a
        plan, list clips, add subtitles, recut, publish, overview). This install runs without
        accounts, so no key is needed.
      </p>

      <div className="flex flex-wrap gap-1.5 mb-4" role="tablist" aria-label="client">
        {clients.map((c) => (
          <button
            key={c.id}
            role="tab"
            aria-selected={c.id === active}
            onClick={() => { setActive(c.id); setCopied(false); }}
            className={`px-3 py-1.5 rounded-input text-xs border transition-colors ${
              c.id === active ? 'border-brass text-ink bg-brass/10' : 'border-rule text-muted hover:text-ink'}`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {current.kind === 'steps' && (
        <ol className="list-decimal pl-5 space-y-1.5 text-sm text-ink2 mb-3">
          {current.steps.map((s) => <li key={s}>{s}</li>)}
        </ol>
      )}

      <div className="relative">
        <pre className={`font-mono text-ink2 whitespace-pre-wrap break-all rounded-card border border-rule bg-paper p-3 pr-20 text-xs ${compact ? '' : 'leading-relaxed'}`}>
          {current.snippet}
        </pre>
        <button onClick={copy} className="btn-ghost absolute top-2 right-2 px-2.5 py-1 text-xs" aria-label="copy">
          {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      {current.note && <p className="text-muted text-xs mt-2">{current.note}</p>}
    </div>
  );
}
