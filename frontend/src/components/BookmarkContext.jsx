// src/components/BookmarkContext.jsx
import React, { createContext, useContext, useState } from "react";

const BookmarkContext = createContext();

export const BookmarkProvider = ({ children }) => {
  const [bookmarks, setBookmarks] = useState([]);

  const addBookmark = (item) => {
    setBookmarks((prev) => [...prev, item]);
  };

  const removeBookmark = (id) => {
    setBookmarks((prev) => prev.filter((item) => item.id !== id));
  };

  return (
    <BookmarkContext.Provider
      value={{ bookmarks, addBookmark, removeBookmark }}
    >
      {children}
    </BookmarkContext.Provider>
  );
};

export const useBookmarks = () => useContext(BookmarkContext);
