// src/App.jsx
import React, { useState, Suspense, lazy } from "react";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { Toaster } from "react-hot-toast";
import AppLayout from "./AppLayout";

// Context providers
import { BookmarkProvider } from "./components/BookmarkContext";
import { TipsProvider } from "./contexts/TipsContext";
import { UserProvider } from "./contexts/UserContext";
import { BetslipProvider } from "./contexts/BetslipContext"; // ✅ ADDED

// Protected route
import ProtectedRoute from "./components/ProtectedRoute";

// Lazy-loaded user pages
const Dashboard = lazy(() => import("./user/Dashboard"));
const Accumulators = lazy(() => import("./user/Accumulators"));
const Predictions = lazy(() => import("./user/Predictions"));
const GroupedPredictions = lazy(() => import("./user/GroupedPredictions"));
const DailyTips = lazy(() => import("./user/DailyTips"));
const ValueTips = lazy(() => import("./user/ValueTips"));
const Results = lazy(() => import("./user/Results"));
const UpcomingMatches = lazy(() => import("./user/UpcomingMatches"));
const Teams = lazy(() => import("./user/Teams"));
const H2H = lazy(() => import("./user/H2H"));
const AuthPage = lazy(() => import("./user/AuthPage"));
const TeamMatchOverview = lazy(() => import("./user/TeamMatchOverviewPage"));
const Bookmarks = lazy(() => import("./user/Bookmarks"));
const VIPPortal = lazy(() => import("./user/VIPPortal"));
const BetslipPage = lazy(() => import("./user/Betslip"));
const Profile = lazy(() => import("./user/Profile"));
const WalletPage = lazy(() => import("./user/WalletPage"));
const MyBetsPage = lazy(() => import("./user/MyBetsPage"));

// Lazy-loaded admin page
const AdminDashboard = lazy(() => import("./admin/AdminDashboard"));

export default function App() {
  const [balance, setBalance] = useState(0);

  return (
    <BookmarkProvider>
      <TipsProvider>
        <UserProvider>
          <BetslipProvider> {/* ✅ FIX: Wrap app with BetslipProvider */}
            <Router>
              {/* Global toaster */}
              <Toaster position="top-right" reverseOrder={false} />

              <Suspense fallback={<div>Loading...</div>}>
                <Routes>
                  {/* AUTH */}
                  <Route path="/auth" element={<AuthPage setBalance={setBalance} />} />

                  {/* PROFILE */}
                  <Route
                    path="/profile"
                    element={
                      <ProtectedRoute>
                        <Profile />
                      </ProtectedRoute>
                    }
                  />

                  {/* BOOKMARKS */}
                  <Route path="/bookmarks" element={<Bookmarks />} />

                  {/* BETSLIP */}
                  <Route
                    path="/betslip"
                    element={
                      <ProtectedRoute>
                        <BetslipPage balance={balance} />
                      </ProtectedRoute>
                    }
                  />

                  {/* MY BETS */}
                  <Route
                    path="/my-bets"
                    element={
                      <ProtectedRoute>
                        <MyBetsPage />
                      </ProtectedRoute>
                    }
                  />

                  {/* LAYOUT ROUTES */}
                  <Route path="/" element={<AppLayout />}>
                    <Route index element={<Dashboard />} />
                    <Route path="predictions" element={<Predictions />} />
                    <Route path="predictions/grouped" element={<GroupedPredictions />} />
                    <Route path="tips/daily" element={<DailyTips />} />
                    <Route path="tips/accumulator" element={<Accumulators />} />
                    <Route path="tips/value" element={<ValueTips />} />
                    <Route path="results" element={<Results />} />
                    <Route path="matches/upcoming" element={<UpcomingMatches />} />
                    <Route path="teams" element={<Teams />} />
                    <Route path="h2h" element={<H2H />} />
                    <Route path="matches/:matchId/overview" element={<TeamMatchOverview />} />
                    <Route path="match-overview" element={<TeamMatchOverview />} />
                    <Route path="vip" element={<VIPPortal />} />
                    <Route path="admin" element={<AdminDashboard />} />

                    {/* WALLET */}
                    <Route
                      path="wallet"
                      element={
                        <ProtectedRoute>
                          <WalletPage balance={balance} />
                        </ProtectedRoute>
                      }
                    />
                  </Route>
                </Routes>
              </Suspense>
            </Router>
          </BetslipProvider>
        </UserProvider>
      </TipsProvider>
    </BookmarkProvider>
  );
}
