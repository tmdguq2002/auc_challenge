import multiprocessing

from lawedit.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()      # exe 에서 PDF 병렬 읽기용
    main()
