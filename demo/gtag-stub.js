// Test stand-in for https://www.googletagmanager.com/gtag/js. This is not Google's code.
// The demo audit serves it instead of the real script so the tests need no network. It mimics
// only what the audit looks at: a cookieless ping carrying gcs while storage is denied, and a
// _ga cookie once analytics_storage is granted. gcs=G1xy, x = ad_storage, y = analytics_storage.
(function () {
  var state = { ad_storage: "-", analytics_storage: "-" };
  var measurementId = null;

  function digit(value) {
    return value === "granted" ? "1" : value === "denied" ? "0" : "-";
  }

  function setAnalyticsCookie() {
    if (!/(^|; )_ga=/.test(document.cookie)) {
      var id = Math.floor(Math.random() * 1e9) + "." + Math.floor(Date.now() / 1000);
      document.cookie = "_ga=GA1.1." + id + "; max-age=63072000; path=/; SameSite=Lax";
    }
  }

  function ping(eventName) {
    var gcs = "G1" + digit(state.ad_storage) + digit(state.analytics_storage);
    new Image().src =
      "https://www.google-analytics.com/g/collect?v=2&tid=" +
      encodeURIComponent(measurementId) + "&en=" + eventName + "&gcs=" + gcs;
  }

  function handle(args) {
    if (args[0] === "consent") {
      ["ad_storage", "analytics_storage"].forEach(function (key) {
        if (args[2] && args[2][key]) state[key] = args[2][key];
      });
      if (args[1] === "update" && measurementId) {
        if (state.analytics_storage === "granted") setAnalyticsCookie();
        ping("user_engagement");
      }
    } else if (args[0] === "config") {
      measurementId = args[1];
      if (state.analytics_storage === "granted") setAnalyticsCookie();
      ping("page_view");
    }
  }

  var dataLayer = (window.dataLayer = window.dataLayer || []);
  dataLayer.forEach(handle);
  var originalPush = dataLayer.push.bind(dataLayer);
  dataLayer.push = function () {
    for (var i = 0; i < arguments.length; i++) handle(arguments[i]);
    return originalPush.apply(null, arguments);
  };
})();
