import React, { useEffect, useState } from "react";
import VirtualAPI from "../api/virtualAPI";

export default function LeagueTable() {
  const [table, setTable] = useState([]);

  useEffect(() => {
    VirtualAPI.getRounds().then((data) => {
      if (data?.table) setTable(data.table);
    });
  }, []);

  return (
    <div className="league-table">
      <h3>League Table</h3>

      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Team</th>
            <th>Pts</th>
          </tr>
        </thead>

        <tbody>
          {table.map((t, i) => (
            <tr key={i}>
              <td>{i + 1}</td>
              <td>{t.team}</td>
              <td>{t.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
