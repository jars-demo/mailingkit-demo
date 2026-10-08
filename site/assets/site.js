// Theme toggle, copy buttons and code tabs. No dependencies.
(function () {
  var root = document.documentElement;

  function currentTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  // The docs menu is expanded for desktop; start it collapsed on small screens.
  if (window.matchMedia("(max-width: 899px)").matches) {
    document.querySelectorAll(".sidebar-menu").forEach(function (menu) {
      menu.open = false;
    });
  }

  var toggle = document.querySelector(".theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try {
        localStorage.setItem("mailingkit-theme", next);
      } catch (error) {}
    });
  }

  document.querySelectorAll("figure.code").forEach(function (figure) {
    var button = figure.querySelector("button.copy");
    var code = figure.querySelector("code");
    if (!button || !code) return;
    button.addEventListener("click", function () {
      var done = function () {
        button.textContent = "Copied";
        setTimeout(function () {
          button.textContent = "Copy";
        }, 1600);
      };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(code.innerText).then(done, function () {});
      }
    });
  });

  document.querySelectorAll(".install-copy").forEach(function (button) {
    button.addEventListener("click", function () {
      var text = button.getAttribute("data-copy") || "";
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(text).then(function () {
        var label = button.querySelector(".install-hint");
        if (!label) return;
        label.textContent = "Copied";
        setTimeout(function () {
          label.textContent = "Copy";
        }, 1600);
      });
    });
  });

  document.querySelectorAll("[data-tabs]").forEach(function (group) {
    var tabs = group.querySelectorAll("[role=tab]");
    var panels = group.querySelectorAll("[role=tabpanel]");
    tabs.forEach(function (tab, index) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (other, i) {
          other.setAttribute("aria-selected", String(i === index));
          other.tabIndex = i === index ? 0 : -1;
          panels[i].hidden = i !== index;
        });
      });
      tab.addEventListener("keydown", function (event) {
        var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        var next = tabs[(index + step + tabs.length) % tabs.length];
        next.focus();
        next.click();
      });
    });
  });

  // Mark the section of the on-this-page list currently in view.
  var tocLinks = document.querySelectorAll(".toc a");
  if (tocLinks.length && "IntersectionObserver" in window) {
    var byId = {};
    tocLinks.forEach(function (link) {
      byId[link.getAttribute("href").slice(1)] = link;
    });
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          tocLinks.forEach(function (link) {
            link.classList.remove("active");
          });
          var link = byId[entry.target.id];
          if (link) link.classList.add("active");
        });
      },
      { rootMargin: "0px 0px -70% 0px" }
    );
    Object.keys(byId).forEach(function (id) {
      var heading = document.getElementById(id);
      if (heading) observer.observe(heading);
    });
  }
})();
