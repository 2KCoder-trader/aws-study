import questionsData from './questions.json';

function sampleQuestions(questions, count) {
  const shuffled = [...questions];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled.slice(0, Math.min(count, shuffled.length));
}

async function handleExplain(request, env) {
  const data = await request.json();
  const { question, choices, correct, user_answer, messages: existingMessages = [] } = data;

  let messages = existingMessages;

  if (messages.length === 0) {
    const choicesFmt = Object.entries(choices).map(([k, v]) => `${k}. ${v}`).join('\n');
    const fullQuestion = `${question}\n\n${choicesFmt}`;
    const correctLetters = correct.split(',');
    const correctText = correctLetters.map(l => `${l}. ${choices[l] || ''}`).join(' | ');

    const userPrompt =
      `AWS exam question:\n${fullQuestion}\n\n` +
      `The student answered: ${user_answer}\n` +
      `The correct answer is: ${correctText}\n\n` +
      `1. Explain why the correct answer is right and why the student's answer is wrong.\n` +
      `2. List the KEY WORDS or phrases in the question that signal the correct answer. Label this section 'Keywords to watch for:'\n` +
      `3. Give one concise exam tip for this topic or question type to help remember on test day. Label this section 'Exam tip:'`;

    messages = [{ role: 'user', content: userPrompt }];
  }

  const anthropicResponse = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: 'claude-opus-4-6',
      max_tokens: 1024,
      stream: true,
      system: 'You are an AWS Solutions Architect exam tutor. Be concise and clear. Use bullet points.',
      messages,
    }),
  });

  if (!anthropicResponse.ok) {
    const err = await anthropicResponse.text();
    return new Response(`data: ${JSON.stringify({ text: `Error: ${err}` })}\n\ndata: ${JSON.stringify({ done: true, messages })}\n\n`, {
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    });
  }

  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const encoder = new TextEncoder();

  (async () => {
    const reader = anthropicResponse.body.getReader();
    const decoder = new TextDecoder();
    let fullResponse = '';
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (raw === '[DONE]') continue;
          try {
            const parsed = JSON.parse(raw);
            if (parsed.type === 'content_block_delta' && parsed.delta?.type === 'text_delta') {
              const text = parsed.delta.text;
              fullResponse += text;
              await writer.write(encoder.encode(`data: ${JSON.stringify({ text })}\n\n`));
            }
          } catch {}
        }
      }

      const updatedMessages = [...messages, { role: 'assistant', content: fullResponse }];
      await writer.write(encoder.encode(`data: ${JSON.stringify({ done: true, messages: updatedMessages })}\n\n`));
    } catch (e) {
      await writer.write(encoder.encode(`data: ${JSON.stringify({ text: `Error: ${e.message}` })}\n\n`));
      await writer.write(encoder.encode(`data: ${JSON.stringify({ done: true, messages })}\n\n`));
    } finally {
      await writer.close();
    }
  })();

  return new Response(readable, {
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
  });
}

async function handleHistory(request, env) {
  const history = (await env.HISTORY.get('history', 'json')) ?? [];
  return Response.json(history);
}

async function handleHistorySave(request, env) {
  const data = await request.json();
  const history = (await env.HISTORY.get('history', 'json')) ?? [];
  const entry = {
    id: history.length + 1,
    date: new Date().toISOString().slice(0, 10),
    start_time: data.start_time,
    end_time: new Date().toTimeString().slice(0, 8),
    duration_seconds: data.duration_seconds,
    score: data.score,
    total: data.total,
    percentage: Math.round((data.score / data.total) * 100),
    questions: data.questions,
  };
  history.push(entry);
  await env.HISTORY.put('history', JSON.stringify(history));
  return Response.json({ ok: true, id: entry.id });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/favicon.ico') {
      return new Response(null, { status: 204 });
    }

    if (url.pathname === '/api/questions') {
      const count = parseInt(url.searchParams.get('count') ?? '10');
      const sample = sampleQuestions(questionsData, count);
      return Response.json({ questions: sample });
    }

    if (url.pathname === '/api/explain' && request.method === 'POST') {
      return handleExplain(request, env);
    }

    if (url.pathname === '/api/history' && request.method === 'GET') {
      return handleHistory(request, env);
    }

    if (url.pathname === '/api/history/save' && request.method === 'POST') {
      return handleHistorySave(request, env);
    }

    // Serve static assets (index.html, etc.)
    return env.ASSETS.fetch(request);
  },
};
