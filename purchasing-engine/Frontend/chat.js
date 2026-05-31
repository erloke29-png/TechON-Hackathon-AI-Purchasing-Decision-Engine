const landingEl = document.getElementById('landing');
const chatEl = document.getElementById('chat');
const landingInput = document.getElementById('landing-input');
const landingSend = document.getElementById('landing-send');
const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendEl = document.getElementById('send');

let conversationHistory = [];

function switchToChat() {
  landingEl.classList.add('hidden');
  chatEl.classList.remove('hidden');
  chatEl.classList.add('flex');
}

function addMessage(role, text) {
  const wrapper = document.createElement('div');
  wrapper.className = 'flex gap-3' + (role === 'user' ? ' justify-end' : '');

  if (role === 'assistant') {
    wrapper.innerHTML = `
      <div style="background-color: #4F6EF7;" class="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0">
        <span class="text-white text-xs font-bold">AI</span>
      </div>
      <div style="background-color: #2C2C2E; border: 1px solid #3A3A3C;" class="rounded-2xl rounded-tl-sm px-4 py-3 max-w-md">
        <p class="text-white text-sm leading-relaxed">${text}</p>
      </div>`;
  } else {
    wrapper.innerHTML = `
      <div style="background-color: #4F6EF7;" class="rounded-2xl rounded-tr-sm px-4 py-3 max-w-md">
        <p class="text-white text-sm leading-relaxed">${text}</p>
      </div>`;
  }

  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return wrapper;
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
      const sessionResponse = await fetch('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profileData)
      });
      const result = await sessionResponse.json();
      window.location.href = `/dashboard?session_id=${result.session_id}`;
    }
  }

  if (inputEl) inputEl.disabled = false;
  if (sendEl) sendEl.disabled = false;
}

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