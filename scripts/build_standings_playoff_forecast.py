#!/usr/bin/env python3
import argparse


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    print(f"WNBA forecast skeleton season={args.season}")


if __name__ == "__main__":
    main()
