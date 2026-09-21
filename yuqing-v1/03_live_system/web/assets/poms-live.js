/* Read-only POMS client used by the GitHub Pages dashboard. No API key is used. */
(function (global) {
  "use strict";

  const BASE_URL = "http://49.233.133.197:8000";
  const TABLE_PATHS = {
    platforms: "overall_and_platform_distribution_statistics",
    regions: "regional_distribution_statistics",
    topContents: "top_10_key_communication_contents",
    trend: "overall_communication_trend",
    classification: "public_opinion_classification_result_details?page=1&page_size=500",
    attitudes: "public_opinion_attitude_statistics_by_platform?page=1&page_size=500",
    problemTypes: "problematic_data_type_statistics?page=1&page_size=500",
    riskItems: "important_problematic_data_details?page=1&page_size=500"
  };

  const number = value => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  };
  const text = value => value == null ? "" : String(value);
  const datePart = value => text(value).slice(0, 10);
  const hourPart = value => text(value).slice(0, 13);
  const nowInChina = () => new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
  }).format(new Date()).replace(" ", "T") + "+08:00";

  function fetchRows(path) {
    return fetch(`${BASE_URL}/api/v1/tables/${path}`, {
      cache: "no-store",
      headers: { Accept: "application/json" }
    }).then(response => {
      if (!response.ok) throw new Error(`POMS ${response.status}`);
      return response.json();
    }).then(data => {
      if (!Array.isArray(data)) throw new Error("POMS returned a non-list payload");
      return data.filter(row => row && typeof row === "object");
    });
  }

  function buildDashboard(source) {
    const platforms = source.platforms.map(row => ({
      name: text(row.platform) || "未标注平台",
      total: number(row.total_information_count), support: 0, neutral: 0, nonSupport: 0, supportRate: 0
    }));
    const provinces = source.regions.map(row => ({
      name: text(row.region) || "未标注地区",
      value: number(row.total_information_count), total: number(row.total_information_count), support: 0
    }));
    const total = platforms.reduce((sum, row) => sum + row.total, 0);
    const publishCount = source.platforms.reduce((sum, row) => sum + number(row.published_content_count), 0);
    const commentCount = source.platforms.reduce((sum, row) => sum + number(row.comment_and_reply_count), 0);
    const daily = new Map();
    const trendHourly = source.trend.map(row => {
      const timestamp = text(row.statistical_time);
      const value = number(row.total_information_count);
      const day = datePart(timestamp);
      if (day) daily.set(day, (daily.get(day) || 0) + value);
      return {
        hour: hourPart(timestamp), label: timestamp.length >= 16 ? timestamp.slice(11, 16) : timestamp,
        date: day, value, heat: number(row.total_interaction_count),
        publishedCount: number(row.published_content_count), commentCount: number(row.comment_and_reply_count)
      };
    }).sort((a, b) => a.hour.localeCompare(b.hour));
    const supportive = source.attitudes.reduce((sum, row) => sum + number(row.supportive_count), 0);
    const neutral = source.attitudes.reduce((sum, row) => sum + number(row.neutral_count), 0);
    const problematic = source.attitudes.reduce((sum, row) => sum + number(row.problematic_count), 0);
    const nonSupport = source.problemTypes.map(row => ({ name: text(row.problem_type) || "未分类问题", value: number(row.total) }));
    const generatedAt = nowInChina();

    return {
      source: { mode: "poms-live", label: "POMS 实时接口", generatedAt }, generatedAt,
      phase: { label: "民族团结进步宣传周", statsStart: "", includeHistory: false, phaseOnly: false },
      topStats: { totalOpinions: total, totalOpinionsLabel: "累计信息数", detectedPlatformCount: platforms.filter(row => row.total > 0).length, detectedPlatformCountAll: platforms.length, detectedRegionCount: provinces.filter(row => row.total > 0).length, supportCount: supportive, nonSupport: problematic },
      stats: { total, publishCount, commentCount, support: supportive, neutral, nonSupport: problematic, regionCount: provinces.filter(row => row.total > 0).length, platformCount: platforms.filter(row => row.total > 0).length, platformCountAll: platforms.length },
      platforms, platformDetail: platforms, regions: provinces, provinces, focusRegions: [],
      trend: Array.from(daily, ([date, value]) => ({ date, value })).sort((a, b) => a.date.localeCompare(b.date)), trendHourly,
      hotTop: source.topContents.map(row => ({ platform: text(row.platform) || "未标注平台", account: text(row.publishing_account) || "未标注发布者", title: text(row.content_title_or_summary), date: datePart(row.published_at), likes: number(row.like_count), comments: number(row.comment_count), shares: number(row.repost_or_share_count), favorites: number(row.favorite_count), url: text(row.original_url) })),
      quotes: source.classification.map(row => ({ platform: text(row.platform) || "未标注平台", text: text(row.core_viewpoint_or_original_text), attitude: text(row.final_category) || text(row.primary_category), issueCategory: text(row.secondary_category), account: text(row.data_id), source: "POMS 分类结果" })),
      attitude: { macro: [{ name: "支持认可", value: supportive }, { name: "中性信息", value: neutral }, { name: "参与建议", value: 0 }, { name: "问题", value: problematic }], detail: nonSupport },
      nonSupport,
      riskItems: source.riskItems.map(row => ({ platform: text(row.platform) || "未标注平台", account: text(row.account) || "未标注账号", text: text(row.content_summary), date: datePart(row.published_at), attitude: "问题", issueCategory: text(row.problem_type), likes: number(row.like_count), comments: number(row.comment_count), shares: number(row.repost_or_share_count), heat: number(row.view_or_play_count) + number(row.like_count) + number(row.comment_count) + number(row.repost_or_share_count), url: text(row.original_url) })),
      keyAccounts: [], languagePlatform: [], unknownPlatforms: [], live: null
    };
  }

  global.POMS_LIVE = {
    load: () => Promise.all(Object.entries(TABLE_PATHS).map(([name, path]) => fetchRows(path).then(rows => [name, rows])))
      .then(entries => buildDashboard(Object.fromEntries(entries))),
    refreshIntervalMs: 30000
  };
})(window);
