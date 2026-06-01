const landingEl = document.getElementById('landing');
const chatEl = document.getElementById('chat');
const landingInput = document.getElementById('landing-input');
const landingSend = document.getElementById('landing-send');
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendEl = document.getElementById('send');

// ─── Persistence ──────────────────────────────────────────────────────────────

let conversationHistory = JSON.parse(localStorage.getItem('chat_messages') || '[]');

function saveHistory() {
  localStorage.setItem('chat_messages', JSON.stringify(conversationHistory));
}

function clearHistory() {
  localStorage.removeItem('chat_messages');
  conversationHistory = [];
}

// ─── Restore chat on page load ────────────────────────────────────────────────

function restoreChat() {
  if (conversationHistory.length === 0) return;
  switchToChat();
  conversationHistory.forEach(msg => {
    renderMessage(msg.role, msg.content);
  });
}

// ─── UI helpers ───────────────────────────────────────────────────────────────

function switchToChat() {
  landingEl.classList.add('hidden');
  chatEl.classList.remove('hidden');
  chatEl.classList.add('flex');
}

function renderMessage(role, text) {
  const displayText = text.includes('INTERVIEW_COMPLETE')
    ? 'Interview complete! Researching the best vendors for you...'
    : text;

  const wrapper = document.createElement('div');
  wrapper.className = 'flex gap-3' + (role === 'user' ? ' justify-end' : '');

  if (role === 'assistant') {
    wrapper.innerHTML = `
      <div class="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0" style="overflow:hidden;background-color:#1C1C1E;">
        <img src="/Frontend/LOGO_Decisio.png" style="width:100%;height:100%;object-fit:cover;" />
      </div>
      <div style="background-color: #2C2C2E; border: 1px solid #3A3A3C;" class="rounded-2xl rounded-tl-sm px-4 py-3 max-w-md">
        <p class="text-white text-sm leading-relaxed">${displayText}</p>
      </div>`;
  } else {
    wrapper.innerHTML = `
      <div style="background-color: #4F6EF7;" class="rounded-2xl rounded-tr-sm px-4 py-3 max-w-md">
        <p class="text-white text-sm leading-relaxed">${displayText}</p>
      </div>`;
  }

  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return wrapper;
}

function addMessage(role, text) {
  return renderMessage(role, text);
}

function startLoadingBar() {
  const bar = document.getElementById('loading-bar');
  const pct = document.getElementById('loading-pct');
  const text = document.getElementById('loading-text');

  const steps = [
    { width: 15, label: 'Analyzing your requirements...' },
    { width: 30, label: 'Finding top vendors...' },
    { width: 50, label: 'Researching pricing and reviews...' },
    { width: 70, label: 'Checking for red flags...' },
    { width: 85, label: 'Building your report...' },
    { width: 95, label: 'Almost done...' }
  ];

  let i = 0;
  const interval = setInterval(() => {
    if (i < steps.length) {
      bar.style.width = steps[i].width + '%';
      pct.textContent = steps[i].width + '%';
      text.textContent = steps[i].label;
      i++;
    } else {
      clearInterval(interval);
    }
  }, 3000);
}

async function sendMessage(text) {
  if (!text.trim()) return;

  switchToChat();
  addMessage('user', text);
  conversationHistory.push({ role: 'user', content: text });
  saveHistory();

  const wrapper = addMessage('assistant', '...');
  const bubble = wrapper.querySelector('p');

  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages: conversationHistory })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let fullText = '';
  bubble.textContent = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    fullText += decoder.decode(value);

    if (fullText.includes('INTERVIEW_COMPLETE')) {
      bubble.textContent = 'Interview complete! Researching the best vendors for you...';
    } else {
      bubble.textContent = fullText;
    }

    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  conversationHistory.push({ role: 'assistant', content: fullText });
  saveHistory();

  if (fullText.includes('INTERVIEW_COMPLETE')) {
    const loadingBubble = document.getElementById('loading-bubble');
    messagesEl.appendChild(loadingBubble);
    loadingBubble.classList.remove('hidden');
    messagesEl.scrollTop = messagesEl.scrollHeight;
    startLoadingBar();

    const match = fullText.match(/---BEGIN_PROFILE---([\s\S]*?)---END_PROFILE---/);
    if (match) {
      let profileData;
      try {
        profileData = JSON.parse(match[1].trim());
      } catch (e) {
        console.error('Failed to parse profile JSON:', e);
        return;
      }

      const startResponse = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...profileData,
          chat_history: conversationHistory
        })
      });

      const startResult = await startResponse.json();
      if (!startResult.session_id) {
        addMessage('assistant', 'Something went wrong. Please try again.');
        return;
      }

      const sessionId = startResult.session_id;
      localStorage.setItem('pending_session_id', sessionId);
      clearHistory();

      const poll = setInterval(async () => {
        try {
          const statusResponse = await fetch(`/api/session/${sessionId}/status`);
          const statusResult = await statusResponse.json();

          if (statusResult.status === 'complete') {
            clearInterval(poll);
            localStorage.removeItem('pending_session_id');
            const loadingBar = document.getElementById('loading-bar');
            if (loadingBar) loadingBar.style.width = '100%';
            const loadingPct = document.getElementById('loading-pct');
            if (loadingPct) loadingPct.textContent = '100%';
            const loadingText = document.getElementById('loading-text');
            if (loadingText) loadingText.textContent = 'Done! Loading your results...';
            setTimeout(() => {
              window.location.href = `/dashboard?session_id=${sessionId}`;
            }, 1500);
          } else if (statusResult.status === 'error' || statusResult.status === 'not_found') {
            clearInterval(poll);
            localStorage.removeItem('pending_session_id');
            addMessage('assistant', `Something went wrong: ${statusResult.error || 'Session not found. Please try again.'}`);
          }
        } catch (e) {
          console.error('Polling error:', e);
        }
      }, 3000);
    }
  }

  if (inputEl) inputEl.disabled = false;
  if (sendEl) sendEl.disabled = false;
}

// ─── Event listeners ──────────────────────────────────────────────────────────

landingSend.addEventListener('click', () => {
  sendMessage(landingInput.value);
  landingInput.value = '';
});

landingInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    sendMessage(landingInput.value);
    landingInput.value = '';
  }
});

sendEl.addEventListener('click', () => {
  sendMessage(inputEl.value);
  inputEl.value = '';
});

inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage(inputEl.value);
    inputEl.value = '';
  }
});

// ─── Restore on load ──────────────────────────────────────────────────────────

const pendingSessionId = localStorage.getItem('pending_session_id');
if (pendingSessionId) {
  switchToChat();
  const loadingBubble = document.getElementById('loading-bubble');
  messagesEl.appendChild(loadingBubble);
  loadingBubble.classList.remove('hidden');

  // Show static message instead of restarting bar from 0%
  const bar = document.getElementById('loading-bar');
  const pct = document.getElementById('loading-pct');
  const text = document.getElementById('loading-text');
  if (bar) bar.style.width = '80%';
  if (pct) pct.textContent = 'Processing...';
  if (text) text.textContent = 'Your report is still being generated — this continues in the background.';

  const resumePoll = setInterval(async () => {
    try {
      const statusResponse = await fetch(`/api/session/${pendingSessionId}/status`);
      const statusResult = await statusResponse.json();

      if (statusResult.status === 'complete') {
        clearInterval(resumePoll);
        localStorage.removeItem('pending_session_id');
        const loadingBar = document.getElementById('loading-bar');
        if (loadingBar) loadingBar.style.width = '100%';
        const loadingPct = document.getElementById('loading-pct');
        if (loadingPct) loadingPct.textContent = '100%';
        const loadingText = document.getElementById('loading-text');
        if (loadingText) loadingText.textContent = 'Done! Loading your results...';
        setTimeout(() => {
          window.location.href = `/dashboard?session_id=${pendingSessionId}`;
        }, 1500);
      } else if (statusResult.status === 'error' || statusResult.status === 'not_found') {
        clearInterval(resumePoll);
        localStorage.removeItem('pending_session_id');
        addMessage('assistant', 'Something went wrong or the session expired. Please try again.');
      }
    } catch (e) {
      console.error('Resume polling error:', e);
    }
  }, 3000);
}

restoreChat();