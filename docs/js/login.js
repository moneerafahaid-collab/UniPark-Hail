const ACCOUNTS = {
  "student@uoh.edu.sa": "طالب تجريبي",
  "faculty@uoh.edu.sa": "عضو هيئة تدريس تجريبي",
  "security@uoh.edu.sa": "أمن الحرم تجريبي"
};

document.getElementById("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const email = String(data.get("email") || "").trim().toLowerCase();
  const password = String(data.get("password") || "");
  const error = document.getElementById("login-error");
  if (ACCOUNTS[email] && password === "hail1234") {
    sessionStorage.setItem("unipark-name", ACCOUNTS[email]);
    window.location.href = "map.html";
    return;
  }
  error.hidden = false;
});
