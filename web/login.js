const form = document.getElementById('loginForm');
const button = form.querySelector('button[type="submit"]');

function showError(message) {
  let error = document.querySelector('.login-error');
  if (!error) {
    error = document.createElement('p');
    error.className = 'login-error';
    error.setAttribute('role', 'alert');
    form.before(error);
  }
  error.textContent = message;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  try {
    const fields = new URLSearchParams(new FormData(form));
    const response = await fetch('/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-RE-Lab-CSRF': fields.get('csrf')},
      body: fields,
    });
    if (response.url.includes('/login?error=1')) {
      showError('번호 또는 암호를 확인하세요.');
      return;
    }
    if (!response.ok) {
      const result = await response.json();
      showError(result.error || '로그인하지 못했습니다. 다시 시도하세요.');
      return;
    }
    const state = await fetch('/api/state', {credentials: 'same-origin', cache: 'no-store'});
    if (!state.ok) {
      showError('이 브라우저가 로그인 세션을 저장하지 못했습니다. 브라우저에서 쿠키를 허용한 뒤 다시 시도하세요.');
      return;
    }
    location.replace('/');
  } catch (_error) {
    showError('연결 오류가 발생했습니다. 잠시 후 다시 시도하세요.');
  } finally {
    button.disabled = false;
  }
});
