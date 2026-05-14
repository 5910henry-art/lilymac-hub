// src/contexts/TipsContext.jsx
import React, { createContext, useState, useEffect, useMemo } from "react";
import api from "../api/api"; // make sure this points to the merged api.js

export const TipsContext = createContext({
  tips: [],
  topCount: 0,
  refreshTips: () => {},
});

export const TipsProvider = ({ children }) => {
  const [tips, setTips] = useState([]);
  const [topCount, setTopCount] = useState(0);

  const fetchTips = async () => {
    try {
      const res = await api.getTipsDaily();
      
      // safely check response
      if (!res || !res.success || !Array.isArray(res.data?.tips)) {
        setTips([]);
        setTopCount(0);
        return;
      }

      // enrich tips with probability %
      const enrichedTips = res.data.tips.map((t) => {
        const probMap = {
          "Home Win": t.probabilities?.home_win,
          "Away Win": t.probabilities?.away_win,
          Draw: t.probabilities?.draw,
        };
        const probability = (probMap[t.prediction] || 0) * 100;
        return { ...t, probability };
      });

      setTips(enrichedTips);
      setTopCount(enrichedTips.filter((t) => t.probability > 60).length);
    } catch (error) {
      console.error("Failed to fetch tips:", error);
      setTips([]);
      setTopCount(0);
    }
  };

  useEffect(() => {
    fetchTips();
  }, []);

  const value = useMemo(() => ({ tips, topCount, refreshTips: fetchTips }), [tips, topCount]);

  return <TipsContext.Provider value={value}>{children}</TipsContext.Provider>;
};
