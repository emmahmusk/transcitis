document.querySelector("#invite-form")?.addEventListener("submit", async event => {
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); data.token = new URLSearchParams(location.search).get("token");
  const error = document.querySelector("#invite-error"), button = event.currentTarget.querySelector("button"); button.disabled = true; error.hidden = true;
  try { const r = await fetch("/api/auth/invitations/accept/", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)}); const result = await r.json(); if(!r.ok) throw new Error(result.detail || Object.values(result).flat().join(" ") || "Invitation could not be accepted."); sessionStorage.setItem("transcitis_access",result.access);sessionStorage.setItem("transcitis_refresh",result.refresh);sessionStorage.setItem("transcitis_user",JSON.stringify(result.user));location.href="/"; }
  catch(e){error.textContent=e.message;error.hidden=false;button.disabled=false;}
});
