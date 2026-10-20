document.querySelector("#login-form")?.addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget), error = document.querySelector("#login-error"), button = event.currentTarget.querySelector("button");
  button.disabled = true; button.textContent = "Signing in…"; error.hidden = true;
  try {
    const response = await fetch("/api/auth/login/", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:form.get("username"),password:form.get("password")})});
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Unable to sign in.");
    sessionStorage.setItem("transcitis_access", data.access); sessionStorage.setItem("transcitis_refresh", data.refresh); sessionStorage.setItem("transcitis_user", JSON.stringify(data.user)); location.href = "/";
  } catch (e) { error.textContent = e.message; error.hidden = false; button.disabled = false; button.innerHTML = "Sign in <span>→</span>"; }
});
